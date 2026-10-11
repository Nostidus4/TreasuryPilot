def test_api_package_imports() -> None:
    import treasurypilot_api

    assert treasurypilot_api.__version__ == "0.1.0"
