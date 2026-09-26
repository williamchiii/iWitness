## Summary
- What changed and why (link the issue this closes, if any: `Fixes #123`)

## Test plan
- [ ] Backend setup from the repository root: `python -m pip install -r server/requirements.txt`, then `python -m pip install -e . --no-deps`
- [ ] `ruff check server` / `npm run lint` passes
- [ ] `python -c "import server.main"` / `npm run build` passes
- [ ] Manually verified: <how you checked this actually works>
