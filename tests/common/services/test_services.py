import pytest
from unittest.mock import MagicMock, patch
from common.services.zephyr_client import ZephyrClient
from common.services.xray_client import XrayClient
from common.services.allure_client import AllureClient
from common.services.test_management_system_client_provider import get_test_management_client
from common.services.test_reporting_client_base_provider import get_test_reporting_client
import config
import os

# Zephyr Client Tests
@pytest.fixture
def zephyr_client():
    with patch("config.ZEPHYR_BASE_URL", "http://zephyr"), \
         patch("config.JIRA_USER", "user"), \
         patch("config.ZEPHYR_API_TOKEN", "token"):
        return ZephyrClient()

def test_zephyr_client_init(zephyr_client):
    assert zephyr_client.base_url == "http://zephyr"

@patch("httpx.Client.get")
def test_zephyr_fetch_test_cases(mock_get, zephyr_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    # Mock statuses response and test cases response
    # The client calls get statuses first, then get test cases.
    
    mock_statuses_resp = MagicMock()
    mock_statuses_resp.status_code = 200
    mock_statuses_resp.json.return_value = {
        "values": [{"id": 1, "name": "Approved", "archived": False}]
    }
    
    mock_tc_resp = MagicMock()
    mock_tc_resp.status_code = 200
    mock_tc_resp.json.return_value = {"values": [], "maxResults": 100}
    
    # We need to handle multiple calls. First call is statuses, second is search.
    # The URL checks in client are: 
    # 1. /statuses...
    # 2. /testcases...
    
    def side_effect(url, **kwargs):
        if "statuses" in url:
            return mock_statuses_resp
        return mock_tc_resp
        
    mock_get.side_effect = side_effect
    
    result = zephyr_client.fetch_ready_for_execution_test_cases_by_labels("PROJ", ["L1"])
    assert isinstance(result, dict)

# Xray Client Tests
@pytest.fixture
def xray_client():
    with patch("config.XRAY_BASE_URL", "http://xray"), \
         patch("config.XRAY_CLIENT_ID", "id"), \
         patch("config.XRAY_CLIENT_SECRET", "secret"), \
         patch("common.services.xray_client.XrayClient._get_token", return_value="mock_token"):
        return XrayClient()

def test_xray_client_init(xray_client):
    assert xray_client.base_url == "http://xray"
    # assert "Bearer mock_token" in xray_client.headers["Authorization"] # Mocking _get_token skips setting headers

@patch("httpx.Client.post")
def test_xray_authenticate(mock_post):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = "real_token"
    mock_response.text = '"real_token"'
    mock_post.return_value = mock_response
    
    with patch("config.XRAY_BASE_URL", "http://xray"), \
         patch("config.XRAY_CLIENT_ID", "id"), \
         patch("config.XRAY_CLIENT_SECRET", "secret"):
         
         client = XrayClient()
         assert "Bearer real_token" in client.xray_headers["Authorization"]

# Allure Client Tests
def test_allure_client_generate_report():
    with patch("os.path.exists", return_value=True), patch("os.makedirs"):
        client = AllureClient("reports")
        with patch("common.services.allure_client.utils.get_logger"):
            with patch("subprocess.run"):
                client.generate_report([])

# Provider Tests
def test_get_test_management_client_zephyr():
    with patch("config.TEST_MANAGEMENT_SYSTEM", "zephyr"), \
         patch("config.ZEPHYR_BASE_URL", "http://zephyr"), \
         patch("config.JIRA_USER", "user"), \
         patch("config.ZEPHYR_API_TOKEN", "token"):
        
        client = get_test_management_client()
        assert isinstance(client, ZephyrClient)

def test_get_test_management_client_xray():
    with patch("config.TEST_MANAGEMENT_SYSTEM", "xray"), \
         patch("config.XRAY_BASE_URL", "http://xray"), \
         patch("config.XRAY_CLIENT_ID", "id"), \
         patch("config.XRAY_CLIENT_SECRET", "secret"), \
         patch("common.services.xray_client.XrayClient._get_token", return_value="token"):
        
        client = get_test_management_client()
        assert isinstance(client, XrayClient)

def test_get_test_reporting_client_allure():
    with patch("config.TEST_REPORTER", "allure"), \
         patch("os.path.exists", return_value=True), patch("os.makedirs"):
        client = get_test_reporting_client("root")
        assert isinstance(client, AllureClient)
