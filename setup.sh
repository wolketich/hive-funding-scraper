#!/bin/bash
# Setup script for Early Years Hive Scraper

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows, use: venv\Scripts\activate

# Install required packages
pip install -r requirements.txt

# Create .env file template if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file template..."
    echo "EMAIL=your_email@example.com" > .env
    echo "PASSWORD=your_password" >> .env
    echo "Please edit the .env file with your actual credentials."
fi

echo "Setup complete! Edit .env with your credentials and run the script with: python early_years_scraper.py"