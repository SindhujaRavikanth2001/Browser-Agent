import httpx
import asyncio
import logging

# Configure logging to see what's happening
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def send_test_message(message_content: str):
    url = "http://localhost:8000/api/message"
    payload = {"content": message_content}
    
    logger.info(f"Sending message to backend: '{message_content}'")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=600)
            response.raise_for_status() # Raise an exception for bad status codes
            
            logger.info(f"Backend response status: {response.status_code}")
            logger.info(f"Backend response body: {response.json()}")
            
    except httpx.RequestError as e:
        logger.error(f"An error occurred while requesting {e.request.url!r}: {e}")
    except httpx.HTTPStatusError as e:
        logger.error(f"Error response {e.response.status_code} while requesting {e.request.url!r}: {e.response.text}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")

async def main():
    # Replace with a message you want the agent to process
    test_message = "Go to https://bidenwhitehouse.archives.gov/briefing-room/presidential-actions/2024/09/26/executive-order-on-combating-emerging-firearms-threats-and-improving-school-based-active-shooter-drills/ and generate survey questions to gauge public opinion on gun violence in schools."
    await send_test_message(test_message)

if __name__ == "__main__":
    asyncio.run(main()) 