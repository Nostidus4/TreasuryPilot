def test_worker_package_imports() -> None:
    import treasurypilot_worker

    assert treasurypilot_worker.__version__ == "0.1.0"
