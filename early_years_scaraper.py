#!/usr/bin/env python3
"""
Production-Ready Early Years Hive Payment Data Scraper

A fast, reliable scraper for Early Years Hive payment data with sorting based
on provider shortcodes and proper Euro symbol handling.

Author: wolketich
Date: 2025-04-30 10:56:50 UTC
"""

import os
import csv
import time
import re
import random
import logging
import traceback
from typing import List, Dict, Optional, Any, Set, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path
from collections import OrderedDict

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, StaleElementReferenceException,
    WebDriverException, ElementClickInterceptedException
)
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
VERSION = "1.1.0"
SCRIPT_START_TIME = datetime.now()
OUTPUT_TIMESTAMP = SCRIPT_START_TIME.strftime("%Y-%m-%d_%H%M%S")
DEFAULT_OUTPUT_FILE = f"early-years-payments-{OUTPUT_TIMESTAMP}.csv"

# Custom provider sort order by shortcode
SHORTCODE_SORT_ORDER = [
    "WF",  # WESTFIELD
    "BP",  # BEECH PARK
    "CH",  # CAPTAINS HILL
    "BL",  # BLANCHARDSTOWN
    "BD",  # BARTON DRIVE
    "TH",  # TAYLORS HILL
    "BR",  # BRAY
    "MM",  # MERRYMEETING
    "SW",  # SWORDS
    "KH",  # KIRVIN HILL
    "SY",  # SANTRY
    "MN",  # MAYNOOTH
    "KY",  # KINSEALY
    "SC",  # SCHOLARSTOWN
    "BW",  # BLACKWOOD
    "BH",  # BARNHALL
    "LW",  # LEDWELL
    "NB",  # NEWBRIDGE
    "GS",  # GREYSTONES
    "GL",  # GREEN-LANE
    "BRM", # BROOMHALL
]

# Mapping of shortcodes to full names for reference
SHORTCODE_TO_NAME = {
    "WF": "WESTFIELD",
    "BP": "BEECH PARK",
    "CH": "CAPTAINS HILL",
    "BL": "BLANCHARDSTOWN",
    "BD": "BARTON DRIVE",
    "TH": "TAYLORS HILL",
    "BR": "BRAY",
    "MM": "MERRYMEETING",
    "SW": "SWORDS",
    "KH": "KIRVIN HILL",
    "SY": "SANTRY",
    "MN": "MAYNOOTH",
    "KY": "KINSEALY",
    "SC": "SCHOLARSTOWN",
    "BW": "BLACKWOOD",
    "BH": "BARNHALL",
    "LW": "LEDWELL",
    "NB": "NEWBRIDGE",
    "GS": "GREYSTONES",
    "GL": "GREEN-LANE",
    "BRM": "BROOMHALL",
}


@dataclass
class FundingItem:
    """Represents a single funding program allocation."""
    programme_call: str
    payment_value: str


@dataclass
class ProviderData:
    """Represents collected data for a single service provider."""
    creche_name: str
    shortcode: str  # Added shortcode field
    funding_data: List[FundingItem]


class EarlyYearsHiveScraper:
    """
    Production-ready scraper for Early Years Hive payment data.
    """
    
    def __init__(self, headless: bool = False, output_file: Optional[str] = None):
        """
        Initialize the scraper with optimized browser configuration.
        
        Args:
            headless: Whether to run the browser in headless mode
            output_file: Custom output file path
        """
        self.output_file = output_file or DEFAULT_OUTPUT_FILE
        
        # Load environment variables
        load_dotenv()
        
        # Validate credentials
        self.email = os.getenv("EMAIL")
        self.password = os.getenv("PASSWORD")
        
        if not self.email or not self.password:
            raise ValueError("Missing credentials in .env file. Please provide EMAIL and PASSWORD.")
        
        # Setup WebDriver with anti-detection measures
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless=new")
            
        # Window size like a typical laptop
        chrome_options.add_argument("--window-size=1366,768")
        
        # Set a common user agent
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36"
        chrome_options.add_argument(f"--user-agent={user_agent}")
        
        # Add anti-detection measures
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        
        # Performance settings
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        
        # Initialize WebDriver
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )
        
        # Modify navigator properties to avoid detection
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """
        })
        
        # Initialize results container
        self.results: List[ProviderData] = []
        
        # Get this week's Wednesday date
        self.target_date = self._get_this_wednesday_date()
        logger.info(f"Target date for payment data: {self.target_date}")
        
        # Track processing stats
        self.stats = {
            "providers_processed": 0,
            "providers_with_data": 0,
            "total_funding_items": 0,
            "unique_funding_programs": set(),
            "start_time": SCRIPT_START_TIME,
        }

    def _get_this_wednesday_date(self) -> str:
        """
        Calculate this week's Wednesday date in DD/MM/YYYY format.
        
        Returns:
            The date string in DD/MM/YYYY format
        """
        now = datetime.now()
        days_until_wednesday = (2 - now.weekday()) % 7  # 2 is Wednesday
        wednesday = now + timedelta(days=days_until_wednesday)
        return wednesday.strftime("%d/%m/%Y")
    
    def _fix_euro_symbol(self, text: str) -> str:
        """Fix Euro symbol encoding issues."""
        if not text:
            return text
        
        # Replace incorrect Euro symbol representations
        fixed_text = text.replace("‚Ç¨", "€")
        fixed_text = fixed_text.replace("&euro;", "€")
        fixed_text = fixed_text.replace("EUR", "€")
        
        return fixed_text
    
    def _extract_shortcode(self, provider_name: str) -> str:
        """
        Extract the shortcode from the provider name.
        
        The shortcode is the second word from the end, before the service provider number.
        Example: "Little Harvard Childcare Ltd. - GL (24KE0503)" -> "GL"
        
        Args:
            provider_name: The full provider name
            
        Returns:
            The extracted shortcode or empty string if not found
        """
        try:
            # Regular expression to match the pattern: something - XX (numbers)
            # where XX is the shortcode
            match = re.search(r'- ([A-Z]+) \(', provider_name)
            if match:
                return match.group(1)
            
            # Alternate method: try to get second word from end (split by spaces)
            parts = provider_name.split()
            if len(parts) >= 3 and "(" in parts[-1]:
                return parts[-2].strip("-()")
            
            # If all fails, return empty string
            return ""
        except Exception as e:
            logger.warning(f"Error extracting shortcode from '{provider_name}': {e}")
            return ""
    
    def _get_sort_index(self, shortcode: str) -> int:
        """
        Get sort index for a provider based on its shortcode.
        
        Args:
            shortcode: The provider shortcode to sort
            
        Returns:
            Index for sorting (lower = first)
        """
        # Clean up shortcode for matching
        clean_code = shortcode.strip().upper()
        
        # Try to find the shortcode in our predefined order
        try:
            return SHORTCODE_SORT_ORDER.index(clean_code)
        except ValueError:
            # If not found, put at the end
            return len(SHORTCODE_SORT_ORDER) + 1
    
    def _handle_cookie_consent(self) -> None:
        """
        Handle cookie consent popup efficiently.
        """
        try:
            # Check if cookie consent popup exists
            cookie_content = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#ccc-content"))
            )
            
            if cookie_content:
                logger.info("Handling cookie consent popup...")
                
                # Find and click reject button
                reject_button = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "#ccc-reject-settings"))
                )
                
                # Quick movement and click
                ActionChains(self.driver).move_to_element(reject_button).click().perform()
                
                # Wait for popup to disappear
                WebDriverWait(self.driver, 5).until_not(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, "#ccc-content"))
                )
                
                logger.info("Cookie consent popup handled")
                
        except TimeoutException:
            # No cookie popup or it has a different structure
            logger.info("No cookie consent popup detected or already handled")
    
    def _fast_type(self, element, text: str) -> None:
        """Type text quickly but with minimal anti-bot detection."""
        # Clear field first
        element.clear()
        
        # Type text in chunks for speed while appearing human
        chunk_size = random.randint(3, 6)
        chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
        
        for chunk in chunks:
            element.send_keys(chunk)
            # Very short delay between chunks
            time.sleep(random.uniform(0.01, 0.05))
    
    def login(self) -> bool:
        """
        Log in to the Early Years Hive portal efficiently.
        
        Returns:
            True if login was successful, False otherwise
        """
        try:
            logger.info("Navigating to the login page...")
            self.driver.get("https://earlyyearshive.ncs.gov.ie/SignIn")
            
            # Wait for page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "Email"))
            )
            
            # Handle cookie consent
            self._handle_cookie_consent()
            
            # Find login form elements
            email_field = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.ID, "Email"))
            )
            password_field = self.driver.find_element(By.ID, "Password")
            
            # Type credentials quickly but naturally
            self._fast_type(email_field, self.email)
            self._fast_type(password_field, self.password)
            
            # Find and click submit button
            submit_button = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.ID, "submit-signin-local"))
            )
            submit_button.click()
            
            # Wait for navigation after login
            login_success = WebDriverWait(self.driver, 15).until(
                lambda d: d.find_elements(By.ID, "current_ServiceProviderID") or 
                        d.find_elements(By.ID, "selectedServiceProvider")
            )
            
            # Check for validation errors
            if self.driver.find_elements(By.CLASS_NAME, "validation-summary-errors"):
                logger.error("Login failed: Invalid credentials")
                return False
                
            logger.info("Login successful")
            return bool(login_success)
            
        except Exception as e:
            logger.error(f"Login failed: {str(e)}")
            self._take_error_screenshot("login_error")
            return False
    
    def _take_error_screenshot(self, error_name: str) -> None:
        """Capture a screenshot when an error occurs for debugging."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"error_{error_name}_{timestamp}.png"
            self.driver.save_screenshot(filename)
            logger.info(f"Error screenshot saved to {filename}")
        except Exception as e:
            logger.warning(f"Failed to take error screenshot: {str(e)}")
    
    def get_service_provider_ids(self) -> List[str]:
        """
        Collect service provider IDs using the exact specified selector.
        
        Returns:
            A list of unique service provider IDs
        """
        logger.info("Collecting service provider IDs...")
        
        try:
            # Wait to ensure page is fully loaded
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "current_ServiceProviderID"))
            )
            
            # Get current service provider ID using the exact specified selector
            current_id = self.driver.execute_script('return document.querySelector("#current_ServiceProviderID").value')
            
            if not current_id:
                raise ValueError("Failed to get current service provider ID")
                
            logger.info(f"Current service provider ID: {current_id}")
            
            # Now get all provider IDs from dropdown
            provider_ids = [current_id]  # Start with current ID
            
            # Click the dropdown to see options
            dropdown_toggle = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".dropdown-toggle"))
            )
            dropdown_toggle.click()
            
            # Wait for dropdown to appear
            WebDriverWait(self.driver, 5).until(
                EC.visibility_of_any_elements_located((By.CSS_SELECTOR, "#provider-dropdown > li"))
            )
            
            # Get the total length of providers as specified
            provider_count = self.driver.execute_script('return document.querySelectorAll("#provider-dropdown > li").length')
            logger.info(f"Provider dropdown count: {provider_count}")
            
            # Get all provider links
            for i in range(1, provider_count + 1):
                # Try to get the provider ID from each link
                try:
                    link_selector = f'#provider-dropdown > li:nth-child({i}) > a'
                    provider_link = self.driver.find_element(By.CSS_SELECTOR, link_selector)
                    href = provider_link.get_attribute("href")
                    
                    if href and "Id=" in href:
                        provider_id = href.split("Id=")[1].split("&")[0] if "&" in href else href.split("Id=")[1]
                        if provider_id and provider_id not in provider_ids:
                            provider_ids.append(provider_id)
                except (NoSuchElementException, StaleElementReferenceException):
                    continue
            
            # Close dropdown by clicking outside
            self.driver.find_element(By.TAG_NAME, "body").click()
            
            logger.info(f"Found {len(provider_ids)} unique service providers")
            return provider_ids
            
        except Exception as e:
            logger.error(f"Error collecting service provider IDs: {str(e)}")
            self._take_error_screenshot("provider_ids_error")
            return []
    
    def process_service_provider(self, provider_id: str) -> Optional[ProviderData]:
        """
        Process a service provider efficiently.
        
        Args:
            provider_id: The ID of the service provider to process
            
        Returns:
            ProviderData object if payments were found, None otherwise
        """
        logger.info(f"Processing service provider ID: {provider_id}")
        self.stats["providers_processed"] += 1
        
        try:
            # Step 1: Change organization using direct URL (more reliable)
            change_url = f"https://earlyyearshive.ncs.gov.ie/Account/Manage/RefreshServiceProvider?Id={provider_id}"
            self.driver.get(change_url)
            
            # Verify the change was successful
            WebDriverWait(self.driver, 10).until(
                lambda d: d.execute_script('return document.querySelector("#current_ServiceProviderID").value') == provider_id
            )
            
            # Handle cookie consent if it appears
            self._handle_cookie_consent()
            
            # Step 2: Go to payments page
            self.driver.get("https://earlyyearshive.ncs.gov.ie/all-payments-issued/")
            
            # Wait for payments table to be present
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "PaymentsReveivedList"))
            )
            
            # Get service provider name
            creche_name = self.driver.find_element(By.ID, "selectedServiceProvider").text.strip()
            
            # Extract shortcode from provider name
            shortcode = self._extract_shortcode(creche_name)
            logger.info(f"Provider: {creche_name}, Shortcode: {shortcode}")
            
            # Step 3: Sort by Processed Date Descending
            sort_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 
                    "#PaymentsReveivedList > div:nth-child(2) > div > div.view-grid.has-pagination.table-responsive > table > thead > tr > th:nth-child(5) > a"))
            )
            sort_button.click()
            
            # Wait for sorting to complete - look for the down arrow
            WebDriverWait(self.driver, 5).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, 
                    "#PaymentsReveivedList > div:nth-child(2) > div > div.view-grid.table-responsive.has-pagination > table > thead > tr > th.sort-enabled.sort.sort-desc > a > span.fa.fa-arrow-down")
            )
            
            # Extract funding data
            funding_data = self._extract_funding_data()
            
            if not funding_data:
                logger.info(f"No payments found for {creche_name} on {self.target_date}")
                return None
            
            # Update stats
            self.stats["providers_with_data"] += 1
            self.stats["total_funding_items"] += len(funding_data)
            for item in funding_data:
                self.stats["unique_funding_programs"].add(item.programme_call)
            
            return ProviderData(creche_name=creche_name, shortcode=shortcode, funding_data=funding_data)
            
        except Exception as e:
            logger.error(f"Error processing service provider {provider_id}: {str(e)}")
            self._take_error_screenshot(f"provider_{provider_id}_error")
            return None
    
    def _extract_funding_data(self) -> List[FundingItem]:
        """
        Extract funding data from the payments table and fix Euro symbols.
        
        Returns:
            List of FundingItem objects for payments on the target date
        """
        funding_data = []
        
        try:
            # Use JavaScript for faster extraction
            table_data = self.driver.execute_script(f"""
                const targetDate = "{self.target_date}";
                const rows = document.querySelectorAll(
                    "#PaymentsReveivedList > div:nth-child(2) > div > div.view-grid.table-responsive.has-pagination > table > tbody > tr"
                );
                const maxRows = Math.min(rows.length, 5);
                const result = [];
                
                for (let i = 0; i < maxRows; i++) {{
                    const cells = rows[i].querySelectorAll('td');
                    if (cells.length >= 6) {{
                        const processedDate = cells[4].textContent.trim();
                        
                        if (processedDate === targetDate) {{
                            result.push({{
                                programmeCall: cells[1].textContent.trim(),
                                paymentValue: cells[5].textContent.trim()
                            }});
                        }}
                    }}
                }}
                
                return result;
            """)
            
            # Convert JavaScript data to Python objects and fix Euro symbol
            for item in table_data:
                payment_value = self._fix_euro_symbol(item['paymentValue'])
                
                funding_data.append(FundingItem(
                    programme_call=item['programmeCall'],
                    payment_value=payment_value
                ))
            
            return funding_data
            
        except Exception as e:
            logger.error(f"Error extracting funding data: {str(e)}")
            return []
    
    def write_to_csv(self, filename: Optional[str] = None) -> None:
        """
        Write collected payment data to a CSV file with shortcode-based sort order.
        
        Args:
            filename: Optional name for the output file
        """
        if not self.results:
            logger.warning("No data to write to CSV")
            return
        
        # Use provided filename or default
        output_file = filename or self.output_file
        
        try:
            # Find all unique funding programs and sort alphabetically
            all_programs = sorted(list(self.stats["unique_funding_programs"]))
            
            # Sort the providers according to their shortcodes
            sorted_results = sorted(self.results, key=lambda x: self._get_sort_index(x.shortcode))
            
            # Prepare data with consistent column ordering
            data = []
            for provider in sorted_results:
                # Format provider name with shortcode for clarity
                formatted_name = provider.creche_name
                row = {"Name": formatted_name}
                
                # Create a mapping of program to payment value for this provider
                payment_map = {item.programme_call: item.payment_value for item in provider.funding_data}
                
                # Add funding allocations for each program in alphabetical order
                for program in all_programs:
                    column_name = f"{program} Allocation"
                    # Get value from the map, applying Euro symbol fix
                    payment_value = self._fix_euro_symbol(payment_map.get(program, ""))
                    row[column_name] = payment_value
                
                data.append(row)
            
            # Create DataFrame with ordered columns
            columns = ["Name"] + [f"{program} Allocation" for program in all_programs]
            df = pd.DataFrame(data)
            
            # Ensure columns are in the right order
            df = df[columns]
            
            # Create a reference dataframe with shortcodes and names
            reference_data = [
                {"Shortcode": code, "Provider Name": name} 
                for code, name in SHORTCODE_TO_NAME.items()
            ]
            reference_df = pd.DataFrame(reference_data)
            
            # Create a detected shortcodes dataframe
            detected_shortcodes = [
                {"Provider Name": r.creche_name, "Detected Shortcode": r.shortcode}
                for r in self.results if r.shortcode
            ]
            detected_df = pd.DataFrame(detected_shortcodes)
            
            # Add metadata
            metadata_df = pd.DataFrame([{
                "Extraction Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Target Payment Date": self.target_date,
                "Total Providers": len(self.results),
                "Script Version": VERSION,
                "User": "wolketich"
            }])
            
            # Write to Excel with multiple sheets for better organization
            excel_file = output_file.replace('.csv', '.xlsx')
            with pd.ExcelWriter(excel_file) as writer:
                df.to_excel(writer, sheet_name="Payment Data", index=False)
                metadata_df.to_excel(writer, sheet_name="Metadata", index=False)
                reference_df.to_excel(writer, sheet_name="Shortcode Reference", index=False)
                detected_df.to_excel(writer, sheet_name="Detected Shortcodes", index=False)
            
            # Also write to CSV for compatibility
            df.to_csv(output_file, index=False, encoding='utf-8-sig')
            
            logger.info(f"Results written to {output_file} and {excel_file}")
            
            # Print summary to console
            print(f"\nExtraction Summary:")
            print(f"------------------")
            print(f"Date: 2025-04-30 10:56:50 (UTC)")
            print(f"User: wolketich")
            print(f"Target payment date: {self.target_date}")
            print(f"Providers processed: {self.stats['providers_processed']}")
            print(f"Providers with data: {self.stats['providers_with_data']}")
            print(f"Unique funding programs: {len(all_programs)}")
            print(f"Total funding items: {self.stats['total_funding_items']}")
            print(f"Output files:")
            print(f"  - CSV: {output_file}")
            print(f"  - Excel: {excel_file}")
            
        except Exception as e:
            logger.error(f"Error writing to CSV: {str(e)}")
            # Try emergency backup
            try:
                emergency_file = f"emergency_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                with open(emergency_file, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['Provider', 'Shortcode', 'Programme', 'Value'])
                    for provider in self.results:
                        for funding in provider.funding_data:
                            writer.writerow([
                                provider.creche_name,
                                provider.shortcode,
                                funding.programme_call,
                                self._fix_euro_symbol(funding.payment_value)
                            ])
                logger.info(f"Emergency backup written to {emergency_file}")
            except Exception as backup_error:
                logger.critical(f"Failed to write emergency backup: {str(backup_error)}")
    
    def run(self) -> None:
        """
        Run the complete scraping process efficiently.
        """
        start_time = datetime.now()
        logger.info(f"Starting scraper at {start_time}")
        
        try:
            # Step 1: Login
            if not self.login():
                logger.error("Cannot proceed due to login failure")
                return
            
            # Step 2: Get service provider IDs
            service_provider_ids = self.get_service_provider_ids()
            if not service_provider_ids:
                logger.error("No service provider IDs found")
                return
            
            # Step 3: Process each service provider
            for idx, provider_id in enumerate(service_provider_ids):
                logger.info(f"Processing provider {idx+1}/{len(service_provider_ids)}")
                provider_data = self.process_service_provider(provider_id)
                if provider_data:
                    self.results.append(provider_data)
            
            # Step 4: Write results to CSV and Excel with shortcode-based sort order
            self.write_to_csv()
            
            # Calculate and log timing information
            end_time = datetime.now()
            duration = end_time - start_time
            logger.info(f"Scraping completed successfully in {duration.total_seconds():.2f} seconds!")
            
        except KeyboardInterrupt:
            logger.warning("Script interrupted by user")
            # Try to save any data collected so far
            if self.results:
                self.write_to_csv(f"partial_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        except Exception as e:
            logger.error(f"An error occurred during scraping: {str(e)}")
            logger.error(traceback.format_exc())
            # Try to save any data collected so far
            if self.results:
                self.write_to_csv(f"error_recovery_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        finally:
            # Clean up
            try:
                self.driver.quit()
                logger.info("Browser closed")
            except:
                logger.warning("Failed to close browser gracefully")


if __name__ == "__main__":
    # Create a friendly console message
    print("=" * 70)
    print("Early Years Hive Payment Data Scraper".center(70))
    print("=" * 70)
    print(f"Current Date and Time (UTC): 2025-04-30 10:56:50")
    print(f"Current User's Login: wolketich")
    print(f"Version: {VERSION}")
    
    # Calculate target date
    now = datetime.now()
    days_until_wednesday = (2 - now.weekday()) % 7
    target_date = now + timedelta(days=days_until_wednesday)
    print(f"Target date for payment data: {target_date.strftime('%d/%m/%Y')}")
    
    print("-" * 70)
    print("Starting scraper...")
    print("-" * 70)
    
    # Run scraper with comprehensive error handling
    try:
        scraper = EarlyYearsHiveScraper(headless=False)
        scraper.run()
    except KeyboardInterrupt:
        print("\nScript terminated by user. Goodbye!")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {str(e)}")
        print("Please check the log file for details.")
    finally:
        print("-" * 70)
        print(f"Script execution complete. Duration: {(datetime.now() - SCRIPT_START_TIME).total_seconds():.2f} seconds")
        print("-" * 70)