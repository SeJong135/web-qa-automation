from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pyautogui
import time

options = Options()
options.add_argument("--window-size=1920,1080")
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option("useAutomationExtension", False)
options.add_experimental_option("detach", True) # 실행 완료 후 브라우저 유지


driver = webdriver.Chrome(options=options)

driver.execute_script(
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
)

try: 

    driver.get("https://portal.wisewires.com/login/login.do")
    driver.refresh()
    wait = WebDriverWait(driver, 10)
    
    user_input = wait.until(
    EC.presence_of_element_located((By.ID, "userId"))
    )
    user_input.send_keys("") # ID 입력

    # 비밀번호 입력
    pw_input = wait.until(
        EC.presence_of_element_located((By.ID, "pw"))
    )
    pw_input.send_keys("") # PW 입력

    driver.execute_script("login();")

    # driver.quit()
    print(f"정상적으로 수행이 완료되었습니다.")
except Exception as e:
    print(f"오류가 발생했습니다: {e}")
