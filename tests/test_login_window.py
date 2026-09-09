from unittest.mock import patch

from app.ui.login_window import LoginWindow


def test_login_email_has_focus_after_construction(qapp):
    window = LoginWindow()
    window.show()
    qapp.processEvents()

    assert qapp.focusWidget() is window.login_email

    window.close()


def test_return_press_in_login_fields_triggers_login(qapp):
    with patch.object(LoginWindow, "_handle_login") as mock_handle_login:
        window = LoginWindow()
        window.login_email.returnPressed.emit()
        window.login_password.returnPressed.emit()

    assert mock_handle_login.call_count == 2


def test_return_press_in_register_fields_triggers_register(qapp):
    with patch.object(LoginWindow, "_handle_register") as mock_handle_register:
        window = LoginWindow()
        window.register_email.returnPressed.emit()
        window.register_password.returnPressed.emit()

    assert mock_handle_register.call_count == 2
