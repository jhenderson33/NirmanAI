import requests
import os

# Define the endpoint (v2 search)
url = "https://api.sam.gov/opportunities/v2/search"

API_KEY = os.environ.get("SAM_KEY")
if not API_KEY:
    raise EnvironmentError("SAM_KEY environment variable is not set.")

params = {
    "api_key": API_KEY,
    # Use the solicitation number you found in the previous step
    "solicitationNumber": "HT941026Q2011",
    "limit": 1
}

try:
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        opps = data.get('opportunitiesData', [])

        if opps:
            opp = opps[0]
            print(f"Project: {opp.get('title')}\n")

            # Extract attachments / resources
            attachments = opp.get('pointOfContact', []) # Fallback check
            # In SAM.gov V2, files are usually listed under 'attachments' or 'resourceLinks'

            # Let's print the web link to the actual documents if found
            ui_link = f"https://sam.gov{opp.get('noticeId')}/view"
            print(f"Direct Web Link to documents: {ui_link}")

            # Print document resource links if provided in the API payload
            if 'attachmentLink' in opp:
                print(f"Attachment Download Link: {opp.get('attachmentLink')}")
            else:
                print("\nRaw attachments are not directly downloadable via this public API key.")
                print("Use the Direct Web Link above to download them manually.")

    else:
        print(f"Error: {response.status_code}")
except Exception as e:
    print(f"An error occurred: {e}")
