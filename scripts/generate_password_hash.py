"""Generate an Argon2id password hash without echoing or storing plaintext."""

from getpass import getpass

from enterprise_ai.security.password import PasswordService


def main() -> None:
    """Prompt twice and print only the resulting password hash."""
    password = getpass("Demonstration password: ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match; no hash was generated.")
    if len(password) < 12:
        raise SystemExit("Use at least 12 characters for demonstration credentials.")
    print("Store this hash in your local .env only; do not commit it:")
    print(PasswordService().hash_password(password))


if __name__ == "__main__":
    main()
