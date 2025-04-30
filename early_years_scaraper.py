#!/usr/bin/env python3
"""
Early Years Hive Payment Data Scraper

This script automates the collection of payment data from the Early Years Hive portal.
It logs in, iterates through all service providers, and collects payment information
for the current week's Wednesday, exporting the results to a CSV file.

Author: wolketich
Date: 2025-04-30
"""

import os
import time
import csv
import logging
from typing import List, Dict, Optional, Any, Set, Tuple
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv


# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class FundingItem:
    """Represents a single funding program allocation."""
    programme_call: str
    payment_value: str


@dataclass
class ProviderData:
    """Represents collected data for a single service provider."""
    creche_name: str
    funding_data: List[FundingItem]


class EarlyYearsHiveScraper:
    """
    A class to scrape payment data from the Early Years Hive portal.
    
    This scraper logs in, collects service provider IDs, and extracts
    payment data for each provider, focusing on payments processed on
    the current week's Wednesday.
    """
    
    def __init__(self, headless: bool = False):
        """
        Initialize the scraper with browser configuration.
        
        Args:
            headless: Whether to run the browser in headless mode (no GUI)
        """
        # Load environment variables
        load_dotenv()
        
        # Check if credentials exist
        self.email = os.getenv("EMAIL")
        self.password = os.getenv("PASSWORD")
        
        if not self.email or not self.password:
            raise ValueError("Missing credentials in .env file. Please provide EMAIL and PASSWORD.")
        
        # Setup WebDriver
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )
        
        # Initialize results container
        self.results: List[ProviderData] = []
        
        # Get this week's Wednesday date
        self.target_date = self._get_this_wednesday_date()
        logger.info(f"Target date for payment data: {self.target_date}")

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
    
    def _handle_cookie_consent(self) -> None:
        """
        Handle the cookie consent popup if it appears.
        """
        try:
            # Wait for the cookie consent dialog to appear
            cookie_content = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#ccc-content"))
            )
            
            # If found, click the "Reject Settings" button
            reject_button = self.driver.find_element(By.CSS_SELECTOR, "#ccc-reject-settings")
            if reject_button:
                logger.info("Handling cookie consent popup...")
                reject_button.click()
                time.sleep(1)  # Small wait to ensure the popup is dismissed
                logger.info("Cookie consent popup handled")
        except (TimeoutException, NoSuchElementException):
            # No cookie popup or it has a different structure - we can proceed
            logger.info("No cookie consent popup detected or already handled")
    
    def login(self) -> bool:
        """
        Log in to the Early Years Hive portal.
        
        Returns:
            True if login was successful, False otherwise
        """
        try:
            logger.info("Navigating to the login page...")
            self.driver.get("https://earlyyearshive.ncs.gov.ie/SignIn")
            
            # Handle cookie consent popup before interacting with login form
            self._handle_cookie_consent()
            
            # Find and fill in login form
            logger.info("Entering login credentials...")
            self.driver.find_element(By.ID, "Email").send_keys(self.email)
            self.driver.find_element(By.ID, "Password").send_keys(self.password)
            
            # Click login button
            logger.info("Submitting login form...")
            self.driver.find_element(By.ID, "submit-signin-local").click()
            
            # Wait for navigation after login
            WebDriverWait(self.driver, 10).until(
                EC.url_contains("earlyyearshive.ncs.gov.ie/")
            )
            
            # Check if login was successful (no error message)
            if not self.driver.find_elements(By.CLASS_NAME, "validation-summary-errors"):
                logger.info("Login successful")
                return True
            
            logger.error("Login failed: Invalid credentials")
            return False
            
        except Exception as e:
            logger.error(f"Login failed: {str(e)}")
            return False
    
    def get_service_provider_ids(self) -> List[str]:
        """
        Collect all service provider IDs from the dropdown menu.
        
        Returns:
            A list of unique service provider IDs
        """
        logger.info("Collecting service provider IDs...")
        try:
            # Get current service provider ID
            current_id = self.driver.find_element(By.ID, "current_ServiceProviderID").get_attribute("value")
            
            # Get all service provider IDs from dropdown
            provider_links = self.driver.find_elements(By.CSS_SELECTOR, "#provider-dropdown > li > a")
            ids = set([current_id])  # Start with current ID
            
            for link in provider_links:
                href = link.get_attribute("href")
                if href and "Id=" in href:
                    provider_id = href.split("Id=")[1].split("&")[0] if "&" in href else href.split("Id=")[1]
                    ids.add(provider_id)
            
            provider_ids = list(ids)
            logger.info(f"Found {len(provider_ids)} unique service providers")
            return provider_ids
            
        except Exception as e:
            logger.error(f"Error collecting service provider IDs: {str(e)}")
            return []
    
    def process_service_provider(self, provider_id: str) -> Optional[ProviderData]:
        """
        Process a single service provider to collect payment data.
        
        Args:
            provider_id: The ID of the service provider to process
            
        Returns:
            ProviderData object if payments were found, None otherwise
        """
        logger.info(f"Processing service provider ID: {provider_id}")
        try:
            # Step 1: Change organization
            self.driver.get(f"https://earlyyearshive.ncs.gov.ie/Account/Manage/RefreshServiceProvider?Id={provider_id}")
            WebDriverWait(self.driver, 10).until(
                EC.url_contains("earlyyearshive.ncs.gov.ie/")
            )
            
            # Handle cookie consent if it appears during navigation
            self._handle_cookie_consent()
            
            # Step 2: Go to payments page
            self.driver.get("https://earlyyearshive.ncs.gov.ie/all-payments-issued/")
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "PaymentsReveivedList"))
            )
            
            # Get service provider name before sorting (in case of page refresh)
            creche_name = self.driver.find_element(By.ID, "selectedServiceProvider").text.strip()
            
            # Step 3: Sort by Processed Date Descending
            sort_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 
                    "#PaymentsReveivedList > div:nth-child(2) > div > div.view-grid.has-pagination.table-responsive > table > thead > tr > th:nth-child(5) > a"))
            )
            sort_button.click()
            
            # Wait for sorting to complete (arrow down icon)
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 
                        "#PaymentsReveivedList > div:nth-child(2) > div > div.view-grid.table-responsive.has-pagination > table > thead > tr > th.sort-enabled.sort.sort-desc > a > span.fa.fa-arrow-down"))
                )
            except TimeoutException:
                logger.warning("Sort indicator not found, continuing anyway")
            
            # Small wait to ensure table is fully loaded after sorting
            time.sleep(1)
            
            # Look for payments from this week's Wednesday
            funding_data = self._extract_funding_data()
            
            if not funding_data:
                logger.info(f"No payments found for {creche_name} on {self.target_date}")
                return None
            
            return ProviderData(creche_name=creche_name, funding_data=funding_data)
            
        except Exception as e:
            logger.error(f"Error processing service provider {provider_id}: {str(e)}")
            return None
    
    def _extract_funding_data(self) -> List[FundingItem]:
        """
        Extract funding data from the payments table for the target date.
        
        Returns:
            List of FundingItem objects for payments on the target date
        """
        funding_data = []
        try:
            # Get all rows from the table
            rows = self.driver.find_elements(By.CSS_SELECTOR, 
                "#PaymentsReveivedList > div:nth-child(2) > div > div.view-grid.table-responsive.has-pagination > table > tbody > tr")
            
            # Limit to first 5 rows as specified
            max_rows = min(len(rows), 5)
            
            for i in range(max_rows):
                row = rows[i]
                cells = row.find_elements(By.TAG_NAME, "td")
                
                # Check if this row matches the target date
                processed_date = cells[4].text.strip()
                if processed_date == self.target_date:
                    programme_call = cells[1].text.strip()
                    payment_value = cells[5].text.strip()
                    funding_data.append(FundingItem(programme_call=programme_call, payment_value=payment_value))
        
        except Exception as e:
            logger.error(f"Error extracting funding data: {str(e)}")
        
        return funding_data
    
    def write_to_csv(self, filename: Optional[str] = None) -> None:
        """
        Write collected payment data to a CSV file.
        
        Args:
            filename: Optional name for the output file
        """
        if not self.results:
            logger.warning("No data to write to CSV")
            return
        
        # Use provided filename or generate one based on current date
        if not filename:
            date_str = datetime.now().strftime("%Y-%m-%d")
            filename = f"early-years-payments-{date_str}.csv"
        
        try:
            # Find all unique funding programs
            all_programs: Set[str] = set()
            for provider in self.results:
                for funding in provider.funding_data:
                    all_programs.add(funding.programme_call)
            
            # Prepare data for pandas DataFrame
            data = []
            for provider in self.results:
                row = {"Name": provider.creche_name}
                
                # Add funding allocations for each program
                for program in all_programs:
                    column_name = f"{program} Allocation"
                    funding_item = next((item for item in provider.funding_data 
                                         if item.programme_call == program), None)
                    row[column_name] = funding_item.payment_value if funding_item else ""
                
                data.append(row)
            
            # Create DataFrame and write to CSV
            df = pd.DataFrame(data)
            df.to_csv(filename, index=False)
            logger.info(f"Results written to {filename}")
            
        except Exception as e:
            logger.error(f"Error writing to CSV: {str(e)}")
    
    def run(self) -> None:
        """
        Run the complete scraping process from login to CSV export.
        """
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
            for provider_id in service_provider_ids:
                provider_data = self.process_service_provider(provider_id)
                if provider_data:
                    self.results.append(provider_data)
            
            # Step 4: Write results to CSV
            self.write_to_csv()
            
            logger.info("Scraping completed successfully!")
            
        except Exception as e:
            logger.error(f"An error occurred during scraping: {str(e)}")
        finally:
            # Clean up
            self.driver.quit()
            logger.info("Browser closed")


if __name__ == "__main__":
    # Create a friendly console message
    print("=" * 60)
    print("Early Years Hive Payment Data Scraper")
    print("=" * 60)
    print(f"Current date and time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"User: {os.getenv('USER', 'wolketich')}")
    print(f"Target date for payment data: {(datetime.now() + timedelta(days=(2 - datetime.now().weekday()) % 7)).strftime('%d/%m/%Y')}")
    print("Starting scraper...")
    print("-" * 60)
    
    # Run scraper with a nice try-except block for friendly error handling
    try:
        scraper = EarlyYearsHiveScraper(headless=False)  # Set to True for production
        scraper.run()
    except KeyboardInterrupt:
        print("\nScript terminated by user. Goodbye!")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {str(e)}")
        print("Please check the log file for details.")
    finally:
        print("-" * 60)
        print("Script execution complete.")