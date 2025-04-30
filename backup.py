#!/usr/bin/env python3
"""
Early Years Hive Funding Finder

This script finds service providers with specific funding types in the Early Years Hive portal.

Author: wolketich
Date: 2025-04-30 13:49:59 UTC
"""

import os
import time
import logging
import re
from typing import List, Dict, Optional, Set, Tuple
from datetime import datetime
from dataclasses import dataclass

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, StaleElementReferenceException
)
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("funding_finder.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
VERSION = "1.3.1"
SCRIPT_START_TIME = datetime.now()
FORMATTED_TIME = SCRIPT_START_TIME.strftime("%Y-%m-%d %H:%M:%S")
OUTPUT_TIMESTAMP = SCRIPT_START_TIME.strftime("%Y-%m-%d_%H%M%S")

TARGET_FUNDING_TYPES = [
    "Core Funding 2024",
    "ECCE 2024",
    "NCS 2024",
    "AIM7 2024",
    "CCSP Saver Programme 2024"
]


@dataclass
class FundingResult:
    provider_id: str
    provider_name: str
    funding_type: str
    data_id: str

@dataclass
class FundingScheduleRow:
    provider_id: str
    provider_name: str
    funding_type: str
    run_date: str
    pay_until: str
    total_due_upto: str
    due_this_period: str
    payable: str
    total_due_incl: str
    allocation_link: str


class EarlyYearsHiveFundingFinder:
    def __init__(self, headless: bool = False):
        load_dotenv()
        self.email = os.getenv("EMAIL")
        self.password = os.getenv("PASSWORD")
        if not self.email or not self.password:
            raise ValueError("Missing credentials in .env file. Please provide EMAIL and PASSWORD.")

        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--window-size=1366,768")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )

        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """
        })

        self.results: List[FundingResult] = []
        self.provider_ids: List[str] = []

    def _handle_cookie_consent(self) -> None:
        try:
            cookie_content = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#ccc-content"))
            )
            if cookie_content:
                reject_button = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "#ccc-reject-settings"))
                )
                reject_button.click()
                WebDriverWait(self.driver, 5).until_not(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, "#ccc-content"))
                )
        except TimeoutException:
            pass

    def login(self) -> bool:
        try:
            logger.info("Navigating to the login page...")
            self.driver.get("https://earlyyearshive.ncs.gov.ie/SignIn")
            WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.ID, "Email")))
            self._handle_cookie_consent()

            email_field = WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable((By.ID, "Email")))
            password_field = self.driver.find_element(By.ID, "Password")
            email_field.clear()
            email_field.send_keys(self.email)
            password_field.clear()
            password_field.send_keys(self.password)

            submit_button = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.ID, "submit-signin-local"))
            )
            submit_button.click()

            login_success = WebDriverWait(self.driver, 15).until(
                lambda d: d.find_elements(By.ID, "current_ServiceProviderID") or
                          d.find_elements(By.ID, "selectedServiceProvider")
            )
            if self.driver.find_elements(By.CLASS_NAME, "validation-summary-errors"):
                logger.error("Login failed: Invalid credentials")
                return False

            logger.info("Login successful")
            return bool(login_success)

        except Exception as e:
            logger.error(f"Login failed: {str(e)}")
            return False

    def get_service_provider_ids(self) -> List[str]:
        logger.info("Collecting service provider IDs...")
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "current_ServiceProviderID"))
            )
            current_id = self.driver.execute_script('return document.querySelector("#current_ServiceProviderID").value')
            if not current_id:
                raise ValueError("Failed to get current service provider ID")
            logger.info(f"Current service provider ID: {current_id}")

            provider_ids = [current_id]
            dropdown_toggle = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".dropdown-toggle"))
            )
            dropdown_toggle.click()

            WebDriverWait(self.driver, 5).until(
                EC.visibility_of_any_elements_located((By.CSS_SELECTOR, "#provider-dropdown > li"))
            )
            provider_count = self.driver.execute_script('return document.querySelectorAll("#provider-dropdown > li").length')

            for i in range(1, provider_count + 1):
                try:
                    link_selector = f'#provider-dropdown > li:nth-child({i}) > a'
                    provider_link = self.driver.find_element(By.CSS_SELECTOR, link_selector)
                    href = provider_link.get_attribute("href")
                    if href and "Id=" in href:
                        provider_id = href.split("Id=")[1].split("&")[0]
                        if provider_id and provider_id not in provider_ids:
                            provider_ids.append(provider_id)
                except (NoSuchElementException, StaleElementReferenceException):
                    continue

            self.driver.find_element(By.TAG_NAME, "body").click()
            logger.info(f"Found {len(provider_ids)} unique service providers")
            return provider_ids

        except Exception as e:
            logger.error(f"Error collecting service provider IDs: {str(e)}")
            return []

    def find_funding_table(self):
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.container.page-body"))
            )
            table = self.driver.execute_script("""
                var tables = document.querySelectorAll('table');
                for (var i = 0; i < tables.length; i++) {
                    var headers = tables[i].querySelectorAll('th');
                    for (var j = 0; j < headers.length; j++) {
                        if (headers[j].textContent.includes('Funding Agreement')) {
                            return tables[i];
                        }
                    }
                }
                return null;
            """)
            return table

        except Exception as e:
            logger.error(f"Error finding funding table: {str(e)}")
            return None

    def check_table_for_funding(self, provider_name: str, provider_id: str) -> List[FundingResult]:
        results = []
        try:
            table = self.find_funding_table()
            if not table:
                logger.warning(f"Could not find funding table for provider {provider_name}")
                return results

            funding_data = self.driver.execute_script("""
                var table = arguments[0];
                var targetTypes = arguments[1];
                var results = [];
                var rows = table.querySelectorAll('tbody > tr');
                for (var j = 0; j < rows.length; j++) {
                    var row = rows[j];
                    var fundingType = row.getAttribute('data-name');
                    var dataId = row.getAttribute('data-id');
                    for (var k = 0; k < targetTypes.length; k++) {
                        if (fundingType === targetTypes[k]) {
                            results.push({ fundingType: fundingType, dataId: dataId });
                            break;
                        }
                    }
                }
                return results;
            """, table, TARGET_FUNDING_TYPES)

            for entry in funding_data:
                results.append(FundingResult(
                    provider_id=provider_id,
                    provider_name=provider_name,
                    funding_type=entry.get('fundingType', ''),
                    data_id=entry.get('dataId', '')
                ))
        except Exception as e:
            logger.error(f"Error checking table for provider {provider_name}: {str(e)}")

        return results

    def search_funding_for_provider(self, provider_id: str) -> List[FundingResult]:
        logger.info(f"Searching funding for provider ID: {provider_id}")
        results = []
        try:
            change_url = f"https://earlyyearshive.ncs.gov.ie/Account/Manage/RefreshServiceProvider?Id={provider_id}"
            self.driver.get(change_url)
            WebDriverWait(self.driver, 10).until(
                lambda d: d.execute_script('return document.querySelector("#current_ServiceProviderID").value') == provider_id
            )
            provider_name = self.driver.find_element(By.ID, "selectedServiceProvider").text.strip()
            self.driver.get("https://earlyyearshive.ncs.gov.ie/programmefunding/")
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.container.page-body"))
            )
            time.sleep(1)

            found_funding_types = set()
            current_page = 1

            while True:
                logger.info(f"Scanning page {current_page}")
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
                )
                time.sleep(1)

                page_results = self.check_table_for_funding(provider_name, provider_id)
                results.extend(page_results)
                found_funding_types.update([r.funding_type for r in page_results])

                if all(t in found_funding_types for t in TARGET_FUNDING_TYPES):
                    logger.info("All target funding types found, stopping early.")
                    break

                try:
                    # Get the last <li> in pagination (it's the "next" button)
                    pagination_items = self.driver.find_elements(By.CSS_SELECTOR, '.pagination li')
                    if not pagination_items or len(pagination_items) < 2:
                        logger.info("No pagination found or only one page.")
                        break

                    next_li = pagination_items[-1]  # last <li>
                    is_disabled = 'disabled' in next_li.get_attribute('class')

                    if is_disabled:
                        logger.info("Next button is disabled — last page reached.")
                        break

                    next_btn = next_li.find_element(By.TAG_NAME, 'a')
                    table_before = self.driver.find_element(By.CSS_SELECTOR, 'table').get_attribute('outerHTML')
                    next_btn.click()

                    WebDriverWait(self.driver, 10).until(
                        lambda d: d.find_element(By.CSS_SELECTOR, 'table').get_attribute('outerHTML') != table_before
                    )
                    current_page += 1

                except Exception as e:
                    logger.warning(f"Failed to go to next page: {e}")
                    break



        except Exception as e:
            logger.error(f"Error searching funding for provider {provider_id}: {str(e)}")

        return results


    def save_results(self, filename: Optional[str] = None) -> None:
        if not self.results:
            logger.warning("No results to save")
            return
        if not filename:
            filename = f"funding_search_results_{OUTPUT_TIMESTAMP}.csv"

        try:
            data = [
                {
                    "Provider ID": r.provider_id,
                    "Provider Name": r.provider_name,
                    "Funding Type": r.funding_type,
                    "Data ID": r.data_id
                }
                for r in self.results
            ]
            df = pd.DataFrame(data)
            df.to_csv(filename, index=False)
            df.to_excel(filename.replace('.csv', '.xlsx'), index=False)
            logger.info(f"Results saved to {filename} and Excel")
        except Exception as e:
            logger.error(f"Error saving results: {str(e)}")

    def run(self) -> None:
        start_time = datetime.now()
        logger.info(f"Starting funding search at {start_time}")
        try:
            if not self.login():
                return
            self.provider_ids = self.get_service_provider_ids()
            if not self.provider_ids:
                return

            for idx, provider_id in enumerate(self.provider_ids):
                logger.info(f"Processing provider {idx+1}/{len(self.provider_ids)}")
                results = self.search_funding_for_provider(provider_id)
                self.results.extend(results)

            self.save_results()

        except KeyboardInterrupt:
            logger.warning("Script interrupted by user")
            if self.results:
                self.save_results(f"partial_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        finally:
            self.driver.quit()
            logger.info("Browser closed")


if __name__ == "__main__":
    print("=" * 70)
    print("Early Years Hive Funding Finder".center(70))
    print("=" * 70)
    print(f"Current Date and Time (UTC - YYYY-MM-DD HH:MM:SS formatted): {FORMATTED_TIME}")
    print(f"Current User's Login: wolketich")
    print(f"Version: {VERSION}")
    print("-" * 70)
    print("Starting funding search...")
    print("-" * 70)

    try:
        finder = EarlyYearsHiveFundingFinder(headless=False)
        finder.run()
    except KeyboardInterrupt:
        print("\nScript terminated by user. Goodbye!")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {str(e)}")
        print("Please check the log file for details.")
    finally:
        print("-" * 70)
        print(f"Script execution complete.")
        print("-" * 70)
