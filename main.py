"""
FastAPI endpoint for Grokipedia search suggestions
Returns autocomplete suggestions from Grokipedia search
"""

from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import time
import logging
import os
import subprocess
import shutil

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try to import webdriver-manager for automatic ChromeDriver management
try:
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.chrome.service import Service as ChromeService
    WEBDRIVER_MANAGER_AVAILABLE = True
except ImportError:
    WEBDRIVER_MANAGER_AVAILABLE = False
    logger.warning("webdriver-manager not available. Install with: pip install webdriver-manager")

# Initialize FastAPI app
app = FastAPI(
    title="Grokipedia Search Suggestions API",
    description="Get autocomplete suggestions from Grokipedia search",
    version="1.0.0"
)


class SuggestionRequest(BaseModel):
    """Request model for search suggestions"""
    query: str
    headless: Optional[bool] = True


class SuggestionResponse(BaseModel):
    """Response model for search suggestions"""
    query: str
    suggestions: List[str]
    count: int
    status: str


def get_chromedriver_path():
    """Find ChromeDriver path, checking common locations for Cloud Run"""
    # Check if chromedriver is in PATH
    chromedriver_path = shutil.which('chromedriver')
    if chromedriver_path:
        logger.info(f"Found ChromeDriver in PATH: {chromedriver_path}")
        return chromedriver_path
    
    # Check common installation paths
    common_paths = [
        '/usr/bin/chromedriver',
        '/usr/local/bin/chromedriver',
        '/opt/chromedriver/chromedriver',
        '/usr/lib/chromium-browser/chromedriver',
    ]
    
    for path in common_paths:
        if os.path.exists(path) and os.access(path, os.X_OK):
            logger.info(f"Found ChromeDriver at: {path}")
            return path
    
    logger.warning("ChromeDriver not found in common paths, Selenium will try to use webdriver-manager")
    return None


def get_grokipedia_suggestions(query: str, headless: bool = True) -> List[str]:
    """
    Search Grokipedia and get all suggestions that appear
    
    Args:
        query: Search term
        headless: Run browser in headless mode (default: True)
    
    Returns:
        List of suggestion texts
    """
    driver = None
    try:
        logger.info(f"Setting up Chrome driver for query: {query}")
        
        # Setup Chrome options for Cloud Run / containerized environments
        chrome_options = Options()
        
        # Essential for headless mode in containers
        if headless:
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--headless=new')  # Use new headless mode
        
        # Required for running in containers (Cloud Run, Docker, etc.)
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--disable-software-rasterizer')
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--disable-background-timer-throttling')
        chrome_options.add_argument('--disable-backgrounding-occluded-windows')
        chrome_options.add_argument('--disable-renderer-backgrounding')
        chrome_options.add_argument('--disable-features=TranslateUI')
        chrome_options.add_argument('--disable-ipc-flooding-protection')
        
        # Window size
        chrome_options.add_argument('--window-size=1920,1080')
        
        # User agent
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        # Binary location (check common Chrome/Chromium paths)
        chrome_binary_paths = [
            '/usr/bin/google-chrome',
            '/usr/bin/chromium-browser',
            '/usr/bin/chromium',
            '/usr/local/bin/chrome',
        ]
        
        for binary_path in chrome_binary_paths:
            if os.path.exists(binary_path):
                chrome_options.binary_location = binary_path
                logger.info(f"Using Chrome binary at: {binary_path}")
                break
        
        # Try to find ChromeDriver
        chromedriver_path = get_chromedriver_path()
        
        # Create service with ChromeDriver
        if chromedriver_path:
            # Use found ChromeDriver
            service = Service(chromedriver_path)
            driver = webdriver.Chrome(service=service, options=chrome_options)
            logger.info(f"Using ChromeDriver from: {chromedriver_path}")
        elif WEBDRIVER_MANAGER_AVAILABLE:
            # Use webdriver-manager to automatically download and manage ChromeDriver
            try:
                service = ChromeService(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=chrome_options)
                logger.info("Using webdriver-manager for ChromeDriver")
            except Exception as e:
                logger.error(f"webdriver-manager failed: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to setup ChromeDriver with webdriver-manager: {str(e)}"
                )
        else:
            # Fallback: Let Selenium try to find ChromeDriver automatically
            try:
                driver = webdriver.Chrome(options=chrome_options)
                logger.info("Using Selenium's automatic ChromeDriver detection")
            except Exception as e:
                logger.error(f"Failed to create Chrome driver: {e}")
                error_msg = (
                    "ChromeDriver not found. Solutions:\n"
                    "1. Install ChromeDriver: apt-get install chromium-chromedriver\n"
                    "2. Install webdriver-manager: pip install webdriver-manager\n"
                    "3. Add ChromeDriver to PATH\n"
                    f"Error: {str(e)}"
                )
                raise HTTPException(
                    status_code=500,
                    detail=error_msg
                )
        
        logger.info(f"Opening Grokipedia...")
        driver.get("https://grokipedia.com/")
        time.sleep(2)
        
        logger.info(f"Searching for: {query}")
        
        # Find search input and type query
        search_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text'], input.w-full"))
        )
        search_input.clear()
        search_input.send_keys(query)
        
        # Wait for suggestions to appear
        logger.info("Waiting for suggestions to appear...")
        time.sleep(2)
        
        # Find all suggestion elements
        suggestions = []
        
        # Try multiple selectors to find suggestions
        selectors = [
            "div[class*='cursor-pointer'] span",
            "div.cursor-pointer span",
            "[role='option']",
            "div[class*='search'] div[class*='result']",
            "div[class*='suggestion']",
            "div[class*='autocomplete'] span",
            "ul[class*='suggestions'] li",
            "div[class*='dropdown'] div"
        ]
        
        for selector in selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    logger.info(f"Found {len(elements)} elements with selector: {selector}")
                    for elem in elements:
                        text = elem.text.strip()
                        if text and len(text) > 2 and text not in suggestions:
                            suggestions.append(text)
                    if suggestions:
                        logger.info(f"Successfully extracted {len(suggestions)} suggestions using selector: {selector}")
                        break
            except Exception as e:
                logger.debug(f"Selector {selector} failed: {e}")
                continue
        
        # If no suggestions found, try to get any visible text elements
        if not suggestions:
            logger.warning("No suggestions found with standard selectors, trying alternative approach...")
            try:
                # Look for any divs or spans that might contain suggestions
                all_elements = driver.find_elements(By.CSS_SELECTOR, "div, span, li")
                for elem in all_elements:
                    text = elem.text.strip()
                    # Filter for likely suggestions (not too long, contains query)
                    if (text and 
                        2 < len(text) < 200 and 
                        query.lower() in text.lower() and 
                        text not in suggestions and
                        text != query):
                        suggestions.append(text)
                        if len(suggestions) >= 10:  # Limit to 10 suggestions
                            break
            except Exception as e:
                logger.error(f"Alternative approach failed: {e}")
        
        return suggestions
        
    except Exception as e:
        logger.error(f"Error getting suggestions: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get suggestions: {str(e)}"
        )
    
    finally:
        if driver:
            try:
                driver.quit()
                logger.info("Browser closed successfully")
            except Exception as e:
                logger.warning(f"Error closing browser: {e}")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Grokipedia Search Suggestions API",
        "version": "1.0.0",
        "endpoints": {
            "/suggestions": "POST - Get search suggestions for a query (requires JSON body)",
            "/health": "GET - Health check"
        }
    }


@app.post("/suggestions", response_model=SuggestionResponse)
async def get_suggestions(request: SuggestionRequest):
    """
    Get autocomplete suggestions from Grokipedia search
    
    Request Body (JSON):
    {
        "query": "search term",
        "headless": true  // optional, default: true
    }
    
    Returns:
        JSON response with suggestions list
    """
    try:
        query = request.query
        headless = request.headless if request.headless is not None else True
        
        logger.info(f"Received request for suggestions: query='{query}', headless={headless}")
        
        if not query or not query.strip():
            raise HTTPException(
                status_code=400,
                detail="Query field is required and cannot be empty"
            )
        
        suggestions = get_grokipedia_suggestions(query.strip(), headless=headless)
        
        logger.info(f"Successfully retrieved {len(suggestions)} suggestions for query: {query}")
        
        return SuggestionResponse(
            query=query.strip(),
            suggestions=suggestions,
            count=len(suggestions),
            status="success"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Grokipedia Search Suggestions API",
        "version": "1.0.0"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
