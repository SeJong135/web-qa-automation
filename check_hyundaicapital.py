from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Set
from urllib.parse import urlparse

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
    Page,
)


# =========================
# 사용자 설정
# =========================
REGISTRANT = "Name"
TEST_ENV = "chrome 145.0.7632.160"
START_URL = "https://www.hyundaicapital.com"
AUTO_START_NO = 1
HEADLESS = False
WAIT_MS = 2500

MAX_SUBITEMS_PER_MENU = 10
HOVER_ONLY_MODE = False

TOP_MENU_TEXTS = [
    "고객센터",
    
]

TARGET_BUTTON_TEXTS = [
    "상환 스케쥴",
    "리스·렌트 세금신고서류",
    "청각 장애인 상담 안내",
    "민원 건수 현황 / 실태평가 결과",
    "개인채무자보호법"
]


# =========================
# 고정 설정
# =========================
SPREADSHEET_URL = ""
WORKSHEET_NAME = "시트1"

BASE_DIR = Path(__file__).resolve().parent
SERVICE_ACCOUNT_FILE = BASE_DIR / "service_account.json"
SCREENSHOT_DIR = BASE_DIR / "screenshots"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# =========================
# 구글 시트
# =========================
def get_worksheet():
    credentials = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES,
    )
    client = gspread.authorize(credentials)
    spreadsheet = client.open_by_url(SPREADSHEET_URL)
    return spreadsheet.worksheet(WORKSHEET_NAME)


def append_row_to_sheet(
    worksheet,
    registrant: str,
    defect_no: str,
    test_env: str,
    defect_title: str,
    defect_content: str,
    image_path: str,
) -> None:
    row = [
        registrant,
        defect_no,
        test_env,
        defect_title,
        defect_content,
        image_path,
    ]
    worksheet.append_row(row, value_input_option="USER_ENTERED")


# =========================
# 유틸
# =========================
def sanitize_filename(text: str) -> str:
    keep = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_"):
            keep.append(ch)
        else:
            keep.append("_")
    return "".join(keep)[:80]


def make_auto_no(index: int) -> str:
    return f"AUTO_{index:02d}"


def is_ignorable_request_failure(url: str) -> bool:
    ignore_keywords = [
        "daum.net",
        "doubleclick.net",
        "google-analytics.com",
        "googletagmanager.com",
        "facebook.net",
        "kakao",
        "googleadservices.com",
    ]
    lower_url = url.lower()
    return any(keyword in lower_url for keyword in ignore_keywords)


def launch_browser(p):
    browser = p.chromium.launch(
        headless=HEADLESS,
        args=["--start-maximized"],
    )
    context = browser.new_context(no_viewport=True)
    return browser, context


def save_screenshot(page: Page, name_hint: str) -> str:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = sanitize_filename(name_hint or "page")
    screenshot_path = str(SCREENSHOT_DIR / f"{timestamp}_{safe_name}.png")
    try:
        page.screenshot(path=screenshot_path, full_page=True)
        return screenshot_path
    except Exception:
        return ""


def format_examples(title: str, items: List[str], max_examples: int = 3) -> List[str]:
    if not items:
        return []

    lines = [f"{title} {len(items)}건"]
    for item in items[:max_examples]:
        lines.append(f"- {item[:300]}")
    return lines


# =========================
# 페이지 모니터
# =========================
class PageMonitor:
    def __init__(self, page: Page, base_domain: str):
        self.page = page
        self.base_domain = base_domain
        self.console_errors: List[str] = []
        self.request_failures: List[str] = []
        self.bad_statuses: List[str] = []
        self.popup_urls: List[str] = []

        self.page.on("console", self._on_console)
        self.page.on("requestfailed", self._on_request_failed)
        self.page.on("response", self._on_response)
        self.page.on("popup", self._on_popup)

    def _on_console(self, msg):
        try:
            if msg.type == "error":
                self.console_errors.append(msg.text)
        except Exception:
            pass

    def _on_request_failed(self, request):
        try:
            if not is_ignorable_request_failure(request.url):
                failure_text = f"{request.method} {request.url}"
                self.request_failures.append(failure_text)
        except Exception:
            pass

    def _on_response(self, response):
        try:
            status = response.status
            target_url = response.url
            netloc = urlparse(target_url).netloc
            if status >= 400 and netloc.endswith(self.base_domain):
                self.bad_statuses.append(f"{status} {target_url}")
        except Exception:
            pass

    def _on_popup(self, popup):
        try:
            popup.wait_for_load_state(timeout=5000)
        except Exception:
            pass

        try:
            self.popup_urls.append(popup.url)
        except Exception:
            self.popup_urls.append("(popup url 확인 실패)")

        try:
            popup.close()
        except Exception:
            pass

    def snapshot(self) -> dict:
        return {
            "console_errors": list(self.console_errors),
            "request_failures": list(self.request_failures),
            "bad_statuses": list(self.bad_statuses),
            "popup_urls": list(self.popup_urls),
        }

    def clear(self) -> None:
        self.console_errors.clear()
        self.request_failures.clear()
        self.bad_statuses.clear()
        self.popup_urls.clear()


# =========================
# 페이지 상태 요약
# =========================
def summarize_current_page(page: Page, monitor: PageMonitor) -> str:
    empty_links: List[str] = []
    new_tab_links: List[str] = []
    button_texts: List[str] = []

    try:
        buttons = page.locator("button")
        btn_count = min(buttons.count(), 12)
        for i in range(btn_count):
            try:
                txt = buttons.nth(i).inner_text().strip()
                if txt:
                    button_texts.append(txt.replace("\n", " "))
            except Exception:
                continue
    except Exception:
        pass

    try:
        anchors = page.locator("a")
        a_count = anchors.count()
        for i in range(a_count):
            try:
                href = anchors.nth(i).get_attribute("href")
                target = anchors.nth(i).get_attribute("target")

                if href is None or href.strip() == "" or href.strip() == "#":
                    empty_links.append("(빈 링크)")
                if target == "_blank" and href:
                    new_tab_links.append(href)
            except Exception:
                continue
    except Exception:
        pass

    snap = monitor.snapshot()

    lines: List[str] = []
    lines.append(f"현재 URL: {page.url}")
    lines.append(f"페이지 제목: {page.title()}")

    lines.extend(format_examples("콘솔 에러", snap["console_errors"], max_examples=3))
    lines.extend(format_examples("네트워크 실패", snap["request_failures"], max_examples=3))
    lines.extend(format_examples("응답 이상(404/500 등)", snap["bad_statuses"], max_examples=3))

    if empty_links:
        lines.append(f"빈 링크 {len(empty_links)}건")

    if new_tab_links:
        lines.append(f"새창 링크(target=_blank) {len(new_tab_links)}건")
        for item in new_tab_links[:3]:
            lines.append(f"- {item[:300]}")

    if snap["popup_urls"]:
        lines.append(f"실제 새창/팝업 열림 {len(snap['popup_urls'])}건")
        for item in snap["popup_urls"][:3]:
            lines.append(f"- {item[:300]}")

    if button_texts:
        lines.append(f"버튼 텍스트: {', '.join(button_texts[:8])}")

    if (
        not snap["console_errors"]
        and not snap["request_failures"]
        and not snap["bad_statuses"]
        and not empty_links
        and not new_tab_links
        and not snap["popup_urls"]
    ):
        lines.append("특이사항 없음")

    return "\n".join(lines)


# =========================
# 공통 액션
# =========================
def load_start_page(page: Page, monitor: PageMonitor) -> Tuple[bool, str]:
    monitor.clear()

    try:
        page.goto(START_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(WAIT_MS)

        if page.url.startswith("about:blank"):
            return False, "메인 진입 후 about:blank 상태"

        return True, f"메인 진입 성공: {page.url}"
    except PlaywrightTimeoutError:
        return False, "메인 진입 타임아웃"
    except Exception as e:
        return False, f"메인 진입 예외: {str(e)[:200]}"


def find_clickable_element_by_text(page: Page, text: str):
    selector_candidates = [
        f"a:has-text('{text}')",
        f"button:has-text('{text}')",
        f"[role='menuitem']:has-text('{text}')",
        f"[role='button']:has-text('{text}')",
        f"li:has-text('{text}')",
        f"span:has-text('{text}')",
    ]

    for selector in selector_candidates:
        locator = page.locator(selector)
        try:
            count = locator.count()
        except Exception:
            continue

        for i in range(count):
            try:
                target = locator.nth(i)
                if target.is_visible():
                    return target, selector
            except Exception:
                continue

    return None, None


def click_with_fallback(page: Page, text: str) -> Tuple[bool, str]:
    target, selector = find_clickable_element_by_text(page, text)
    if target is None:
        return False, f"대상 없음: {text}"

    try:
        before_url = page.url
        target.scroll_into_view_if_needed()
        target.click(timeout=5000)
        page.wait_for_timeout(WAIT_MS)
        after_url = page.url
        return True, f"클릭 성공 | selector={selector} | before={before_url} | after={after_url}"
    except Exception as e:
        return False, f"클릭 실패 | selector={selector} | reason={str(e)[:180]}"


def prioritize_subitems(subitems: List[str]) -> List[str]:
    priority_items: List[str] = []
    normal_items: List[str] = []

    for item in subitems:
        matched = False
        for keyword in TARGET_BUTTON_TEXTS:
            if keyword in item or item in keyword:
                priority_items.append(item)
                matched = True
                break
        if not matched:
            normal_items.append(item)

    final_list: List[str] = []
    seen: Set[str] = set()

    for item in priority_items:
        if item not in seen:
            seen.add(item)
            final_list.append(item)

    for item in normal_items:
        if item not in seen:
            seen.add(item)
            final_list.append(item)
        if len(final_list) >= MAX_SUBITEMS_PER_MENU:
            break

    return final_list[:MAX_SUBITEMS_PER_MENU]


def hover_menu_and_collect_subitems(page: Page, menu_text: str) -> Tuple[bool, str, List[str]]:
    target, selector = find_clickable_element_by_text(page, menu_text)
    if target is None:
        return False, f"hover 대상 없음: {menu_text}", []

    try:
        target.scroll_into_view_if_needed()
        target.hover(timeout=5000)
        page.wait_for_timeout(WAIT_MS)
    except Exception as e:
        return False, f"hover 실패: {str(e)[:180]}", []

    collected: List[str] = []
    seen: Set[str] = set()

    candidates = page.locator("a:visible, button:visible, [role='menuitem']:visible, [role='button']:visible")
    try:
        count = min(candidates.count(), 200)
    except Exception:
        count = 0

    ignore_words = [
        "로그인", "검색", "전체메뉴", "닫기", "이전", "다음",
        "회사소개", "인재채용", "채용", "윤리경영", "개인정보처리방침",
        "이용약관", "상품공시", "전자민원", "사업자정보", "SNS", "유튜브",
    ]

    for i in range(count):
        try:
            el = candidates.nth(i)
            txt = el.inner_text().strip().replace("\n", " ")
            if not txt:
                continue

            if txt == menu_text:
                continue
            if len(txt) > 30:
                continue
            if len(txt) < 2:
                continue
            if txt in ignore_words:
                continue
            if txt in seen:
                continue

            seen.add(txt)
            collected.append(txt)
        except Exception:
            continue

    prioritized = prioritize_subitems(collected)
    return True, f"hover 성공 | selector={selector} | 수집 {len(prioritized)}건", prioritized


def click_subitem_and_record(
    page: Page,
    monitor: PageMonitor,
    top_menu_text: str,
    subitem_text: str,
) -> Tuple[str, str, str]:
    monitor.clear()

    start_url = page.url
    start_title = page.title() or "제목없음"
    start_dt = datetime.now()

    clicked, click_detail = click_with_fallback(page, subitem_text)

    end_dt = datetime.now()
    load_time_sec = round((end_dt - start_dt).total_seconds(), 2)

    current_url = page.url
    current_title = page.title() or "제목없음"
    moved = current_url != start_url

    screenshot_path = save_screenshot(page, f"{top_menu_text}_{subitem_text}_{current_title}")
    page_summary = summarize_current_page(page, monitor)

    defect_title = f"[자동점검][상단메뉴:{top_menu_text}] {subitem_text}"

    lines: List[str] = []
    lines.append(f"상단 메뉴: {top_menu_text}")
    lines.append(f"하위 클릭 대상: {subitem_text}")
    lines.append(f"시작 URL: {start_url}")
    lines.append(f"시작 제목: {start_title}")
    lines.append(f"클릭 결과: {click_detail}")
    lines.append(f"이동 여부: {'이동함' if moved else '이동 안 함'}")
    lines.append(f"도착 URL: {current_url}")
    lines.append(f"도착 제목: {current_title}")
    lines.append(f"소요 시간: {load_time_sec}초")
    lines.append("")
    lines.append("페이지 상태 요약")
    lines.append(page_summary)
    lines.append("")
    lines.append("콘솔/네트워크 설명")
    lines.append("1. 콘솔 에러는 브라우저 콘솔에 찍힌 프론트엔드/리소스 오류임")
    lines.append("2. 네트워크 실패는 요청 자체가 실패한 경우임")
    lines.append("3. 응답 이상은 같은 도메인 요청 중 404/500 등 상태코드 오류를 의미함")
    lines.append("")
    lines.append("수행 절차")
    lines.append("1. 메인 페이지 진입")
    lines.append(f"2. 상단 메뉴 '{top_menu_text}' hover")
    lines.append(f"3. hover 후 노출된 하위 항목 '{subitem_text}' 클릭")
    lines.append("4. 이동/오류/링크/버튼 상태 확인")
    lines.append("")
    lines.append("예상 결과")
    lines.append("1. 메뉴 hover 후 하위 항목이 정상 노출되어야 함")
    lines.append("2. 하위 항목 클릭 시 정상 이동 또는 동작해야 함")
    lines.append("3. 치명적인 콘솔 에러/핵심 네트워크 실패/응답 이상이 없어야 함")

    defect_content = "\n".join(lines)
    return defect_title, defect_content, screenshot_path


def inspect_top_menu(page: Page, monitor: PageMonitor, top_menu_text: str) -> List[Tuple[str, str, str]]:
    results: List[Tuple[str, str, str]] = []

    start_ok, start_detail = load_start_page(page, monitor)

    if not start_ok:
        defect_title = f"[자동점검][상단메뉴:{top_menu_text}] 시작 실패"
        defect_content = (
            f"상단 메뉴: {top_menu_text}\n"
            f"시작 상태: {start_detail}\n"
            f"예상 결과: 메인 페이지가 정상 로드되어야 함"
        )
        screenshot_path = save_screenshot(page, f"start_fail_{top_menu_text}")
        results.append((defect_title, defect_content, screenshot_path))
        return results

    monitor.clear()
    hovered, hover_detail, subitems = hover_menu_and_collect_subitems(page, top_menu_text)

    if not hovered:
        screenshot_path = save_screenshot(page, f"hover_fail_{top_menu_text}")
        defect_title = f"[자동점검][상단메뉴] {top_menu_text} hover 실패"
        defect_content = (
            f"상단 메뉴: {top_menu_text}\n"
            f"hover 결과: {hover_detail}\n"
            f"예상 결과: 메뉴 hover 시 하위 항목이 노출되어야 함"
        )
        results.append((defect_title, defect_content, screenshot_path))
        return results

    if not subitems:
        screenshot_path = save_screenshot(page, f"hover_no_subitems_{top_menu_text}")
        defect_title = f"[자동점검][상단메뉴] {top_menu_text} 하위 항목 없음"
        defect_content = (
            f"상단 메뉴: {top_menu_text}\n"
            f"hover 결과: {hover_detail}\n"
            f"하위 항목 수집 결과: 0건\n"
            f"예상 결과: hover 후 클릭 가능한 하위 항목이 보여야 함"
        )
        results.append((defect_title, defect_content, screenshot_path))
        return results

    screenshot_path = save_screenshot(page, f"hover_open_{top_menu_text}")
    defect_title = f"[자동점검][상단메뉴] {top_menu_text} hover 결과"
    defect_content = (
        f"상단 메뉴: {top_menu_text}\n"
        f"hover 결과: {hover_detail}\n"
        f"수집된 하위 항목 수: {len(subitems)}\n"
        f"수집된 하위 항목: {', '.join(subitems)}\n"
        f"우선순위 기준: {', '.join(TARGET_BUTTON_TEXTS)}\n"
        f"메뉴당 최대 점검 수: {MAX_SUBITEMS_PER_MENU}"
    )
    results.append((defect_title, defect_content, screenshot_path))

    if HOVER_ONLY_MODE:
        return results

    for subitem_text in subitems:
        start_ok, start_detail = load_start_page(page, monitor)
        if not start_ok:
            screenshot_path = save_screenshot(page, f"reload_fail_{top_menu_text}_{subitem_text}")
            defect_title = f"[자동점검][상단메뉴:{top_menu_text}] {subitem_text} 시작 실패"
            defect_content = (
                f"상단 메뉴: {top_menu_text}\n"
                f"하위 클릭 대상: {subitem_text}\n"
                f"시작 상태: {start_detail}"
            )
            results.append((defect_title, defect_content, screenshot_path))
            continue

        hovered_again, hover_detail_again, _ = hover_menu_and_collect_subitems(page, top_menu_text)
        if not hovered_again:
            screenshot_path = save_screenshot(page, f"rehover_fail_{top_menu_text}_{subitem_text}")
            defect_title = f"[자동점검][상단메뉴:{top_menu_text}] {subitem_text} 재-hover 실패"
            defect_content = (
                f"상단 메뉴: {top_menu_text}\n"
                f"하위 클릭 대상: {subitem_text}\n"
                f"재-hover 결과: {hover_detail_again}"
            )
            results.append((defect_title, defect_content, screenshot_path))
            continue

        results.append(click_subitem_and_record(page, monitor, top_menu_text, subitem_text))

    return results


# =========================
# 실행
# =========================
def main():
    print("시트 연결 중...")
    worksheet = get_worksheet()

    with sync_playwright() as p:
        browser, context = launch_browser(p)
        page = context.new_page()

        base_domain = urlparse(START_URL).netloc
        monitor = PageMonitor(page, base_domain)

        auto_no_counter = AUTO_START_NO

        for top_menu_text in TOP_MENU_TEXTS:
            print(f"\n상단 메뉴 점검 중: {top_menu_text}")
            records = inspect_top_menu(page, monitor, top_menu_text)

            for defect_title, defect_content, screenshot_path in records:
                defect_no = make_auto_no(auto_no_counter)
                append_row_to_sheet(
                    worksheet=worksheet,
                    registrant=REGISTRANT,
                    defect_no=defect_no,
                    test_env=TEST_ENV,
                    defect_title=defect_title,
                    defect_content=defect_content,
                    image_path=screenshot_path,
                )
                print(f"시트 입력 완료: {defect_no} | {defect_title}")
                auto_no_counter += 1

        context.close()
        browser.close()

    print("\n전체 완료")


if __name__ == "__main__":
    main()