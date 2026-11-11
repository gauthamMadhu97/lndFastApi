import warnings

# Starlette suggests httpx2 for its TestClient; httpx still works fine.
# Set here because the warning is raised when conftest imports TestClient.
warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")
