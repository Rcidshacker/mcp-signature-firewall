# Gates: M0 scaffold and statistics

OWNS: pyproject.toml, src/sigfw/stats.py, src/sigfw/cli.py, src/sigfw/__init__.py, tests/test_stats.py, scripts/gates.py, .gitignore, .gitattributes, .env.example, README.md

Scope: the repository installs, lints, type-checks and tests clean, the pre-registered Wilson values reproduce, and secrets hygiene is enforced.

- [x] G1: all tests pass
  CHECK: uv run python scripts/gates.py tests
  EXPECT: TESTS_OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=9af1ac2c55db5eb2917c9ee659a5f68cd1cc6bd56f77d08379fdaca97d17ce72; exit=0; EXPECT=matched; output-sha256=70ea310a9e8f219e4729c7e296e8bd72cc0c8436dd55ea6fdffddfd793751ade; output-bytes=31; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Lenovo\Desktop\Code\2026\mcp-signature-firewall; path=60bee5be6be7/50 entries

- [x] G2: lint clean
  CHECK: uv run ruff check .
  EXPECT: All checks passed!
  EVIDENCE: automatic-evidence=v1; definition-sha256=304de969ad2d7b880ac1c92eac805b6231dcb383090814d38560ae64c3676104; exit=0; EXPECT=matched; output-sha256=82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18; output-bytes=19; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Lenovo\Desktop\Code\2026\mcp-signature-firewall; path=60bee5be6be7/50 entries

- [x] G3: types clean
  CHECK: uv run mypy src tests
  EXPECT: Success: no issues found
  EVIDENCE: automatic-evidence=v1; definition-sha256=4c7be1d20988aac3f095e787d5ea87bde7ba8f13b4144e5b8b20200365cebe79; exit=0; EXPECT=matched; output-sha256=d9a5631f7d87a741fbecc3236286d1792d22d349ff13846d71cdc9217307bb76; output-bytes=44; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Lenovo\Desktop\Code\2026\mcp-signature-firewall; path=60bee5be6be7/50 entries

- [x] G4: pre-registered Wilson values reproduce
  CHECK: uv run python -c "from sigfw.stats import wilson_upper as w; print('WILSON', [round(w(a, b) * 100, 2) for a, b in [(6, 200), (7, 200), (12, 300), (13, 300)]])"
  EXPECT: WILSON [6.39, 7.05, 6.86, 7.27]
  EVIDENCE: automatic-evidence=v1; definition-sha256=3a1f230eee11cf4e9382a9496c6329a241a5b79c4ac29f00598a70b3c435e37b; exit=0; EXPECT=matched; output-sha256=f7f4f9644fa4cbbb2daa0706d63b4d9a8a2e8ee06d07c8aceeb107b4d1284d14; output-bytes=33; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Lenovo\Desktop\Code\2026\mcp-signature-firewall; path=60bee5be6be7/50 entries

- [x] G5: .env is gitignored
  CHECK: uv run python scripts/gates.py env-ignored
  EXPECT: ENV_IGNORED_OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=86935c3ccc1f70b3de9dd253de233d09cc8e84b2b328f3d2eccb50c7f8522bbc; exit=0; EXPECT=matched; output-sha256=2d6e58870d839b0b4fc1afdce2d77a365c041d9b7eba0dfb7c51e412b4c52d51; output-bytes=16; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Lenovo\Desktop\Code\2026\mcp-signature-firewall; path=60bee5be6be7/50 entries

- [x] G6: .env.example is NOT gitignored (so it can be committed)
  CHECK: uv run python scripts/gates.py env-example-tracked
  EXPECT: ENV_EXAMPLE_OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=45e886e62a24227ab4771bed636f853ce5100e13f02c94cf9fc2b01ed2a216ea; exit=0; EXPECT=matched; output-sha256=ba878f49ec711ffa1c9b00fccd187a9b6163c22d8df8f271e179d3d54e40db27; output-bytes=16; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Lenovo\Desktop\Code\2026\mcp-signature-firewall; path=60bee5be6be7/50 entries

- [x] G7: no NVIDIA key pattern in the tree
  CHECK: uv run python scripts/gates.py no-keys
  EXPECT: NO_KEYS_OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=6e79e496f78808e57ba50b53a174598ef5751a2b6f8bca5c76beeac297dd321f; exit=0; EXPECT=matched; output-sha256=a7bf2c825f80ddfd5ea35c36ff572d3ca6e1d79692c36c34d1e41037bcb1daec; output-bytes=12; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Lenovo\Desktop\Code\2026\mcp-signature-firewall; path=60bee5be6be7/50 entries
