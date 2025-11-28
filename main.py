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
import time
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        
        # Setup Chrome options
        chrome_options = Options()
        if headless:
            chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        driver = webdriver.Chrome(options=chrome_options)
        
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
