import pytest

from changerisk.models import Severity
from changerisk.rules.security import entropy, find_secrets, looks_real, mask

from .helpers import change, run_rule

# Built from pieces so this file does not itself trip secret scanners.
AWS = "AKIA" + "QWERTYUIOPASDFGH"
GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
STRIPE = "sk_" + "live_" + "4eC39HqLyjWDarjtT1zdp7dc"
PRIVATE = "-----BEGIN " + "RSA PRIVATE KEY-----"


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        (f'aws_key = "{AWS}"', "AWS access key id"),
        (f"token: {GH}", "GitHub token"),
        (f"STRIPE={STRIPE}", "Stripe live key"),
        (PRIVATE, "private key"),
        ('password = "Zx9!kQ72mPw4"', "hard-coded password"),
        ('"api_key": "f81d4fae7dec11d0a765"', "hard-coded api_key"),
    ],
)
def test_find_secrets_positive(text, kind):
    assert kind in [k for k, _, _ in find_secrets(text)]


@pytest.mark.parametrize(
    "text",
    [
        'password = "changeme123"',
        'password = "your-password-here"',
        'token = "${GITHUB_TOKEN}"',
        'secret = os.environ["SECRET_KEY_VALUE"]',
        'api_key = "xxxxxxxxxxxxxxxx"',
        'password = "short"',
        'secret_name = "abcdefghijkl"',  # letters only, no digits
        "AKIAIOSFODNN7EXAMPLE",  # the documented example key
        'description = "reset your password after login"',
    ],
)
def test_find_secrets_negative(text):
    assert find_secrets(text) == []


def test_mask_and_entropy_helpers():
    assert mask("sk_live_abcdef123456") == "sk_l" + "*" * 12
    assert mask("abcd") == "a***"
    assert entropy("aaaa") == 0
    assert looks_real("Zx9kQ72mPw4aL")
    assert not looks_real("aaaaaaaa1")


def test_sec001_masks_the_value_everywhere():
    cs = change({"src/pay.py": ("x = 1\n", f'x = 1\nKEY = "{STRIPE}"\n')})
    (f,) = run_rule("SEC001", cs)
    assert f.severity == Severity.CRITICAL
    blob = f.detail + " ".join(e.text for e in f.evidence)
    assert STRIPE not in blob and "4eC39HqLyjWDarjtT1zdp7dc" not in blob
    assert "sk_l" in blob
    assert f.evidence[0].line == 2


def test_sec001_generic_assignment_is_high_not_critical():
    cs = change({"app/conf.py": ("", 'DB_PASSWORD = "Zx9kQ72mPw4aL"\n')})
    assert run_rule("SEC001", cs)[0].severity == Severity.HIGH


def test_sec001_only_looks_at_added_lines():
    cs = change({"src/pay.py": (f'KEY = "{STRIPE}"\n', "KEY = None\n")})
    assert run_rule("SEC001", cs) == []


def test_sec001_inline_ignore():
    cs = change({"src/pay.py": ("", f'KEY = "{STRIPE}"  # changerisk: ignore SEC001\n')})
    assert run_rule("SEC001", cs) == []


def test_sec001_private_key_in_a_pem_file_and_keystore_file():
    cs = change({"deploy/server.pem": (None, f"{PRIVATE}\nMIIE...\n")})
    assert run_rule("SEC001", cs)[0].severity == Severity.CRITICAL
    store = change({"deploy/app.p12": (None, "binary-ish\n")})
    assert "credential store" in run_rule("SEC001", store)[0].detail


def test_sec001_public_certificate_is_not_a_secret():
    cs = change(
        {
            "deploy/server.pem": (
                None,
                "-----BEGIN CERTIFICATE-----\nMIIE\n-----END CERTIFICATE-----\n",
            )
        }
    )
    assert run_rule("SEC001", cs) == []


def test_sec001_fixture_tokens_in_tests_are_downgraded_when_generic():
    cs = change({"tests/test_login.py": ("", 'PASSWORD = "Zx9kQ72mPw4aL"\n')})
    assert run_rule("SEC001", cs)[0].severity == Severity.MEDIUM


def test_sec002_groups_files_by_area():
    cs = change({
        "src/auth/sessions.py": ("a\n", "b\n"),
        "src/auth/tokens.py": ("a\n", "b\n"),
        "src/billing/invoice.py": ("a\n", "b\n"),
        "src/util.py": ("a\n", "b\n"),
    })  # fmt: skip
    found = run_rule("SEC002", cs)
    assert sorted(f.title for f in found) == [
        "Sensitive area modified: authentication",
        "Sensitive area modified: billing",
    ]
    auth = next(f for f in found if f.title.endswith("authentication"))
    assert auth.paths == ["src/auth/sessions.py", "src/auth/tokens.py"]


def test_sec002_file_name_alone_can_place_a_file_in_an_area():
    cs = change({"src/util/session_store.py": ("a\n", "b\n")})
    assert run_rule("SEC002", cs)[0].title.endswith("sessions")


def test_sec002_big_changes_escalate_and_tests_docs_are_ignored():
    big = "".join(f"line {i}\n" for i in range(90))
    cs = change(
        {
            "src/payments/charge.py": ("", big),
            "tests/test_payments.py": ("", big),
            "docs/auth.md": ("", big),
        }
    )
    (f,) = run_rule("SEC002", cs)
    assert f.severity == Severity.HIGH
    assert f.paths == ["src/payments/charge.py"]


def test_sec002_camel_case_and_configured_paths():
    from changerisk.config import Config

    camel = change({"src/UserSession.ts": ("a\n", "b\n")})
    assert run_rule("SEC002", camel)[0].title.endswith("sessions")
    cfg = Config(sensitive=("src/ledger/**",))
    cs = change({"src/ledger/post.py": ("a\n", "b\n")})
    assert "marked sensitive" in run_rule("SEC002", cs, cfg)[0].title


@pytest.mark.parametrize(
    "snippet",
    [
        "requests.get(url, verify=False)",
        "const agent = new https.Agent({ rejectUnauthorized: false })",
        "tls.Config{InsecureSkipVerify: true}",
        "ctx.check_hostname = False",
        "curl -k https://internal",
        "ssh -o StrictHostKeyChecking=no host",
    ],
)
def test_sec003_patterns(snippet):
    cs = change({"src/client.py": ("", snippet + "\n")})
    assert len(run_rule("SEC003", cs)) == 1


def test_sec003_comments_docs_and_tests():
    assert run_rule("SEC003", change({"src/c.py": ("", "# verify=False is bad\n")})) == []
    assert run_rule("SEC003", change({"docs/tls.md": ("", "use verify=False\n")})) == []
    in_tests = change({"tests/test_c.py": ("", "requests.get(u, verify=False)\n")})
    assert run_rule("SEC003", in_tests)[0].severity == Severity.MEDIUM
