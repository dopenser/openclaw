# CDP Automation Server

A Chrome DevTools Protocol (CDP) based automation server for browser control and function calling.

## Features

- Chrome Automation: Launch and control Chrome instances via CDP
- Function Calling: Execute JavaScript functions in browser context
- Session Management: Handle multiple browser sessions
- License Verification: Built-in license checking mechanism
- API Key Authentication: Secure access control

## Requirements

- Python 3.7+
- Chrome/Chromium browser
- Required Python packages (see installation)

## Installation

1. Clone the repository:
bash
git clone https://github.com/dopenser/openclaw.git
cd openclaw


2. Install dependencies:
bash
pip install -r requirements.txt


Required packages:
- websocket-client
- requests
- python-dotenv

## Configuration

1. API Key: Edit api.key file with your API key
2. License: Generate license using generate_license.py
3. Model Config: Adjust model_config.py for AI model settings

## Usage

### Start the Server

bash
python server.py


The server will start on default port (configured in model_config.py).

### Launch Chrome Instance

bash
python chrome_launcher.py


### Execute Functions

Use function_call.py to execute JavaScript functions in the browser:

python
from function_call import FunctionCall

fc = FunctionCall()
result = fc.call("document.title")


### Generate License

bash
python generate_license.py


### Verify License

bash
python lic_verifier.py


## Project Structure

- server.py - Main server endpoint
- cdp_client.py - CDP client implementation
- chrome_launcher.py - Chrome instance launcher
- function_call.py - JavaScript function executor
- session.py - Session management
- model_config.py - Configuration settings
- prompt.py - Prompt templates
- lic_verifier.py - License verification
- generate_license.py - License generator
- generate_keys.py - Key pair generator
- api.key - API key file

## API Endpoints

(Add your specific API endpoints here based on server.py implementation)

## Security Notes

- Keep api.key secure and never commit it to public repositories
- Regenerate license keys regularly
- Use HTTPS in production
- Implement rate limiting for production use

## Troubleshooting

Chrome won't launch: Ensure Chrome is installed and in PATH

Connection refused: Check if Chrome remote debugging port is available

License invalid: Regenerate license using generate_license.py

## License

This project is proprietary software. See license file for details.

## Support

For issues or questions, please open an issue on GitHub.
