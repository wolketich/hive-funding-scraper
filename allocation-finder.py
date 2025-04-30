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
VERSION = "1.3.0"
SCRIPT_START_TIME = datetime.now()
FORMATTED_TIME = SCRIPT_START_TIME.strftime("%Y-%m-%d %H:%M:%S")
OUTPUT_TIMESTAMP = SCRIPT_START_TIME.strftime("%Y-%m-%d_%H%M%S")

# Funding types to search for
TARGET_FUNDING_TYPES = [
    "Core Funding 2024",
    "ECCE 2024",
    "NCS 2024",
    "AIM7 2024",
    "CCSP Saver Programme 2024"
]


@dataclass
class FundingResult:
    """Represents a funding search result."""
    provider_id: str
    provider_name: str
    funding_type: str
    data_id: str


class EarlyYearsHiveFundingFinder:
    """
    Script to find service providers with specific funding types.
    """
    
    def __init__(self, headless: bool = False):
        """
        Initialize the funding finder with browser configuration.
        
        Args:
            headless: Whether to run the browser in headless mode
        """
        # Load environment variables
        load_dotenv()
        
        # Validate credentials
        self.email = os.getenv("EMAIL")
        self.password = os.getenv("PASSWORD")
        
        if not self.email or not self.password:
            raise ValueError("Missing credentials in .env file. Please provide EMAIL and PASSWORD.")
        
        # Setup WebDriver
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless=new")
            
        # Set window size
        chrome_options.add_argument("--window-size=1366,768")
        
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
        
        # Initialize results
        self.results: List[FundingResult] = []
        self.provider_ids: List[str] = []
        
    def _handle_cookie_consent(self) -> None:
        """Handle cookie consent popup if it appears."""
        try:
            cookie_content = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#ccc-content"))
            )
            
            if cookie_content:
                logger.info("Handling cookie consent popup...")
                reject_button = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "#ccc-reject-settings"))
                )
                reject_button.click()
                
                # Wait for popup to disappear
                WebDriverWait(self.driver, 5).until_not(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, "#ccc-content"))
                )
                logger.info("Cookie consent popup handled")
                
        except TimeoutException:
            # No cookie popup
            pass
    
    def login(self) -> bool:
        """
        Log in to the Early Years Hive portal.
        
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
            
            # Enter login credentials
            logger.info("Entering login credentials...")
            email_field = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.ID, "Email"))
            )
            password_field = self.driver.find_element(By.ID, "Password")
            
            email_field.clear()
            email_field.send_keys(self.email)
            
            password_field.clear()
            password_field.send_keys(self.password)
            
            # Click login button
            submit_button = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.ID, "submit-signin-local"))
            )
            submit_button.click()
            
            # Wait for login to complete
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
            return False
    
    def get_service_provider_ids(self) -> List[str]:
        """
        Collect all service provider IDs.
        
        Returns:
            A list of unique service provider IDs
        """
        logger.info("Collecting service provider IDs...")
        
        try:
            # Wait to ensure page is fully loaded
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "current_ServiceProviderID"))
            )
            
            # Get current service provider ID
            current_id = self.driver.execute_script('return document.querySelector("#current_ServiceProviderID").value')
            
            if not current_id:
                raise ValueError("Failed to get current service provider ID")
                
            logger.info(f"Current service provider ID: {current_id}")
            
            # Get all provider IDs from dropdown
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
            
            # Get all provider links
            provider_count = self.driver.execute_script('return document.querySelectorAll("#provider-dropdown > li").length')
            logger.info(f"Provider dropdown count: {provider_count}")
            
            for i in range(1, provider_count + 1):
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
            return []
    
    def find_funding_table(self) -> Optional[webdriver.remote.webelement.WebElement]:
        """
        Find the funding table using a simple and reliable approach.
        
        Returns:
            WebElement for the table or None if not found
        """
        try:
            # Wait for the page to fully load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.container.page-body"))
            )
            
            # Simple direct approach - find the table that contains "Funding Agreement"
            # This works regardless of the table's position in the DOM
            table = self.driver.execute_script("""
                // Get all tables in the page
                var tables = document.querySelectorAll('table');
                
                // Find the one with "Funding Agreement" in the header
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
            
            if table:
                logger.info("Found funding table")
                return table
            
            logger.warning("No funding table found")
            return None
            
        except Exception as e:
            logger.error(f"Error finding funding table: {str(e)}")
            return None
    
    def check_table_for_funding(self, provider_name: str, provider_id: str) -> List[FundingResult]:
        """
        Check the current table for target funding types.
        
        Args:
            provider_name: Name of the current provider
            provider_id: ID of the current provider
            
        Returns:
            List of funding results found on current page
        """
        results = []
        
        try:
            # Find the funding table
            table = self.find_funding_table()
            
            if not table:
                logger.warning(f"Could not find funding table for provider {provider_name}")
                return results
            
            # Use JavaScript to find target funding types and extract data
            funding_data = self.driver.execute_script("""
                var table = arguments[0];
                var targetTypes = arguments[1];
                var results = [];
                
                // Check all rows
                var rows = table.querySelectorAll('tbody > tr');
                
                for (var j = 0; j < rows.length; j++) {
                    var row = rows[j];
                    var fundingType = row.getAttribute('data-name');
                    var dataId = row.getAttribute('data-id');
                    
                    // Check if this is one of our target funding types
                    for (var k = 0; k < targetTypes.length; k++) {
                        if (fundingType === targetTypes[k]) {
                            results.push({
                                fundingType: fundingType,
                                dataId: dataId
                            });
                            break;
                        }
                    }
                }
                
                return results;
            """, table, TARGET_FUNDING_TYPES)
            
            if not funding_data:
                logger.info(f"No target funding found for provider {provider_name}")
                return results
                
            logger.info(f"Found {len(funding_data)} target funding entries")
            
            # Process the JavaScript results
            for entry in funding_data:
                funding_type = entry.get('fundingType', '')
                data_id = entry.get('dataId', '')
                
                logger.info(f"Found target funding: {funding_type} with ID: {data_id}")
                
                results.append(FundingResult(
                    provider_id=provider_id,
                    provider_name=provider_name,
                    funding_type=funding_type,
                    data_id=data_id
                ))
        
        except Exception as e:
            logger.error(f"Error checking table for provider {provider_name}: {str(e)}")
        
        return results
    
    def search_funding_for_provider(self, provider_id: str) -> List[FundingResult]:
        """
        Search for specific funding types for a service provider.
        
        Args:
            provider_id: The service provider ID
            
        Returns:
            List of funding results found
        """
        logger.info(f"Searching funding for provider ID: {provider_id}")
        results = []
        
        try:
            # Change to the specified provider
            change_url = f"https://earlyyearshive.ncs.gov.ie/Account/Manage/RefreshServiceProvider?Id={provider_id}"
            self.driver.get(change_url)
            
            # Verify the change was successful
            WebDriverWait(self.driver, 10).until(
                lambda d: d.execute_script('return document.querySelector("#current_ServiceProviderID").value') == provider_id
            )
            
            # Get provider name
            provider_name = self.driver.find_element(By.ID, "selectedServiceProvider").text.strip()
            logger.info(f"Processing provider: {provider_name}")
            
            # Go to programme funding page
            self.driver.get("https://earlyyearshive.ncs.gov.ie/programmefunding/")
            
            # Ensure page is fully loaded by waiting for main container
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.container.page-body"))
            )
            
            # Give page a moment to fully render
            time.sleep(1)
            
            # Check the table for target funding
            page_results = self.check_table_for_funding(provider_name, provider_id)
            results.extend(page_results)
            
            return results
            
        except Exception as e:
            logger.error(f"Error searching funding for provider {provider_id}: {str(e)}")
            return []
    
    def save_results(self, filename: Optional[str] = None) -> None:
        """
        Save the funding search results to a file.
        
        Args:
            filename: Optional custom filename
        """
        if not self.results:
            logger.warning("No results to save")
            return
        
        # Default filename if none provided
        if not filename:
            filename = f"funding_search_results_{OUTPUT_TIMESTAMP}.csv"
        
        try:
            # Prepare data for DataFrame
            data = [
                {
                    "Provider ID": result.provider_id,
                    "Provider Name": result.provider_name,
                    "Funding Type": result.funding_type,
                    "Data ID": result.data_id
                }
                for result in self.results
            ]
            
            # Create and save DataFrame
            df = pd.DataFrame(data)
            df.to_csv(filename, index=False)
            
            # Also save as Excel
            excel_file = filename.replace('.csv', '.xlsx')
            df.to_excel(excel_file, index=False)
            
            logger.info(f"Results saved to {filename} and {excel_file}")
            
            # Print summary
            print(f"\nSearch Summary:")
            print(f"--------------")
            print(f"Total providers: {len(self.provider_ids)}")
            print(f"Providers with target funding: {len(set(result.provider_id for result in self.results))}")
            print(f"Total funding entries found: {len(self.results)}")
            print(f"Results saved to:")
            print(f"  - CSV: {filename}")
            print(f"  - Excel: {excel_file}")
            
        except Exception as e:
            logger.error(f"Error saving results: {str(e)}")
    
    def run(self) -> None:
        """Run the funding search process."""
        start_time = datetime.now()
        logger.info(f"Starting funding search at {start_time}")
        
        try:
            # Step 1: Login
            if not self.login():
                logger.error("Cannot proceed due to login failure")
                return
            
            # Step 2: Get all service provider IDs
            self.provider_ids = self.get_service_provider_ids()
            if not self.provider_ids:
                logger.error("No service provider IDs found")
                return
            
            # Step 3: Search funding for each provider
            for idx, provider_id in enumerate(self.provider_ids):
                logger.info(f"Processing provider {idx+1}/{len(self.provider_ids)}")
                results = self.search_funding_for_provider(provider_id)
                self.results.extend(results)
            
            # Step 4: Save results
            self.save_results()
            
            # Calculate timing
            end_time = datetime.now()
            duration = end_time - start_time
            logger.info(f"Search completed in {duration.total_seconds():.2f} seconds")
            
        except KeyboardInterrupt:
            logger.warning("Script interrupted by user")
            # Save partial results
            if self.results:
                self.save_results(f"partial_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        except Exception as e:
            logger.error(f"An error occurred: {str(e)}")
            logger.error(f"Error details: {str(e)}")
        finally:
            # Clean up
            self.driver.quit()
            logger.info("Browser closed")


if __name__ == "__main__":
    # Print header
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