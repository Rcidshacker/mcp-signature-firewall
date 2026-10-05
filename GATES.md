# Gates: M0 scaffold and statistics

OWNS: pyproject.toml, src/sigfw/stats.py, src/sigfw/cli.py, src/sigfw/__init__.py, tests/test_stats.py, scripts/gates.py, .gitignore, .gitattributes, .env.example, README.md

Scope: the repository installs, lints, type-checks and tests clean, the pre-registered Wilson values reproduce, and secrets hygiene is enforced.

- [x] G1: all tests pass
  CHECK: uv run python scripts/gates.py tests
  EXPECT: TESTS_OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=9af1ac2c55db5eb2917c9ee659a5f68cd1cc6bd56f77d08379fdaca97d17ce72; exit=0; EXPECT=matched; output-sha256=8be296e4c6ac475680d52d09fb266a0302819b6f3592f911f23a299c1084490c; output-bytes=33; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Lenovo\Desktop\Code\2026\mcp-signature-firewall; path=60bee5be6be7/50 entries

- [x] G2: lint clean
  CHECK: uv run ruff check .
  EXPECT: All checks passed!
  EVIDENCE: automatic-evidence=v1; definition-sha256=304de969ad2d7b880ac1c92eac805b6231dcb383090814d38560ae64c3676104; exit=0; EXPECT=matched; output-sha256=82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18; output-bytes=19; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Lenovo\Desktop\Code\2026\mcp-signature-firewall; path=60bee5be6be7/50 entries

- [x] G3: types clean
  CHECK: uv run mypy src tests
  EXPECT: Success: no issues found
  EVIDENCE: automatic-evidence=v1; definition-sha256=4c7be1d20988aac3f095e787d5ea87bde7ba8f13b4144e5b8b20200365cebe79; exit=0; EXPECT=matched; output-sha256=706935f02fed95e8e0241ec13fa86be727783ee491ba3e8e4470ceaeed6232d8; output-bytes=45; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Lenovo\Desktop\Code\2026\mcp-signature-firewall; path=60bee5be6be7/50 entries

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

- [x] G8: no prompt file precedes the pinned shadowing commit (strict ancestor, and the set passes check-own at that commit)
  CHECK: uv run python scripts/gates.py prompt-order
  EXPECT: PROMPT_ORDER_OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=e1db8aaf8597f8f801b358b592a5beb100e73fbe92536215b2fff6b78c6479d6; exit=0; EXPECT=matched; output-sha256=df1ba5714d9c556fda6f6be929c92173f9b037bb9d5685f4f049d9c62043d7f2; output-bytes=102; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Lenovo\Desktop\Code\2026\mcp-signature-firewall; path=60bee5be6be7/50 entries

- [x] G9: the author-written shadowing set is complete (n is 35 or more across both authors, no duplicates or near-duplicates)
  CHECK: uv run sigfw data check-own
  EXPECT: /shadowing n=(3[5-9]|[4-9][0-9])/
  EVIDENCE: automatic-evidence=v1; definition-sha256=96f974f608675a4bab8dac9688e1ff0339735250c794e586faf3a641012cf30d; exit=0; EXPECT=matched; output-sha256=4dd569616150e53000a39be0a8a1d9699978164f196f44bf987ca8b29d9c12d6; output-bytes=580; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Lenovo\Desktop\Code\2026\mcp-signature-firewall; path=60bee5be6be7/50 entries

- [ ] G10: the protocol check enforces the ordering and passes [pending M4: `sigfw eval protocol --check` fails unless G8 and G11 hold]
  CHECK: uv run sigfw eval protocol --check
  EXPECT: PROTOCOL_OK

- [x] G11: the frozen quoting slice commit is a strict ancestor of the protocol-freeze commit (vacuous until protocol.toml exists)
  CHECK: uv run python scripts/gates.py freeze-order
  EXPECT: FREEZE_ORDER_OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=9c003f91506d7587d894ac46ce185357a1de64137b03f4175604e532b3f2ffa9; exit=0; EXPECT=matched; output-sha256=ea3d44f4ed97fb87dac7c0971e73374b60db68d9a344f9eba8d1f6144cd40ffe; output-bytes=60; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Lenovo\Desktop\Code\2026\mcp-signature-firewall; path=60bee5be6be7/50 entries

- [ ] G12: check-quoting passes on both slices (frozen: exactly 200 reviewed rows; dev: 40 to 60 rows) [pending: the author writes the slices]
  CHECK: uv run python scripts/gates.py quoting
  EXPECT: QUOTING_BOTH_OK
