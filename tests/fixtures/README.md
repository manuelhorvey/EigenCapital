# Contract Test Fixtures

To capture a live bundle for contract testing:

```bash
curl http://127.0.0.1:5000/state-bundle.json | python3 -m json.tool > tests/fixtures/bundle_live.json
```

Run contract tests:

```bash
pytest tests/test_api_contract.py -v
```
