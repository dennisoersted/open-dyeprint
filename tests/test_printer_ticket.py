from opendyeprint.printer import set_ticket_borderless, ticket_borderless

TICKET = """<psf:PrintTicket><psf:Feature name="psk:PageBorderless">
<psf:Option name="psk:None" /></psf:Feature></psf:PrintTicket>"""


def test_turn_borderless_on_and_off():
    on, ok = set_ticket_borderless(TICKET, True)
    assert ok and ticket_borderless(on) is True
    off, ok = set_ticket_borderless(on, False)
    assert ok and ticket_borderless(off) is False


def test_unsupported_ticket_untouched():
    t = "<psf:PrintTicket></psf:PrintTicket>"
    assert set_ticket_borderless(t, True) == (t, False)
    assert ticket_borderless(t) is None
