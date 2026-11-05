from __future__ import annotations

import uuid

from app.core.email_verification import generate_verification_code, verification_code_hash, verify_code


def test_verification_code_has_six_digits_and_is_activation_bound():
    activation_a, activation_b = uuid.uuid4(), uuid.uuid4()
    code = generate_verification_code()
    assert len(code) == 6 and code.isdigit()
    stored = verification_code_hash(activation_a, code)
    assert verify_code(activation_a, code, stored)
    assert not verify_code(activation_a, "000000" if code != "000000" else "000001", stored)
    assert not verify_code(activation_b, code, stored)
    assert code not in stored
