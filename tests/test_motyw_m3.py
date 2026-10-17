"""Motyw M3 całej aplikacji (unowocześnienie 16.10.2026): komponenty z motywu, arkusz dolny
z uchwytem, gest „wstecz” na formularzu, menu FAB z pigułek."""

import asyncio

import flet as ft

import db
import pomoce
import utils


def _motywy():
    return utils.zbuduj_motyw(ft.Colors.INDIGO), utils.zbuduj_motyw(ft.Colors.INDIGO, oled=True)


def test_motyw_niesie_komponenty_m3():
    for motyw in _motywy():
        assert motyw.page_transitions.android == ft.PageTransitionTheme.PREDICTIVE
        assert motyw.progress_indicator_theme.year_2023 is False
        assert motyw.slider_theme.year_2023 is False
        assert motyw.snackbar_theme.behavior == ft.SnackBarBehavior.FLOATING
        assert motyw.bottom_sheet_theme.clip_behavior == ft.ClipBehavior.ANTI_ALIAS
        assert motyw.appbar_theme.elevation == 0 and motyw.appbar_theme.elevation_on_scroll
        assert ft.ControlState.SELECTED in motyw.switch_theme.thumb_icon


def test_czysta_czern_zostaje_czarna_takze_w_arkuszach(baza):
    db.zapisz_czysta_czern(True)
    motyw = utils.zbuduj_motyw_ciemny(ft.Colors.INDIGO)
    assert motyw.scaffold_bgcolor == utils.POWIERZCHNIE_OLED["surface"]
    assert motyw.appbar_theme.bgcolor == utils.POWIERZCHNIE_OLED["surface"]
    assert motyw.bottom_sheet_theme.bgcolor == utils.POWIERZCHNIE_OLED["surface_container_low"]

    db.zapisz_czysta_czern(False)
    assert utils.zbuduj_motyw_ciemny(ft.Colors.INDIGO).scaffold_bgcolor is None


def test_zastosuj_motywy_wgrywa_ten_sam_wyglad_w_obu_trybach(baza):
    strona = pomoce.zbuduj_strone()
    utils.zastosuj_motywy(strona.page, "Zielony")
    for motyw in (strona.page.theme, strona.page.dark_theme):
        assert motyw.color_scheme_seed == ft.Colors.GREEN
        assert motyw.page_transitions == utils.PRZEJSCIA_EKRANOW


def test_paski_gorne_biora_tlo_z_motywu(baza):
    """Pasek z własnym `bgcolor` nie podbarwiłby się pod przewijaną treścią."""
    strona = pomoce.zbuduj_strone()
    stan = pomoce.stan_aplikacji()
    glowny = utils.zbuduj_pasek_glowny(strona.page, stan, None, None, None)
    z_powrotem = utils.zbuduj_pasek_z_powrotem(strona.page, "Ekran", "/")
    assert glowny.bgcolor is None and z_powrotem.bgcolor is None
    assert all(p.width is None for p in glowny.actions if isinstance(p, ft.IconButton)), "cel dotyku 48 dp"


def test_arkusz_dolny_ma_uchwyt_i_tlo_z_motywu(monkeypatch):
    otwarte = []
    monkeypatch.setattr(utils.dialogi, "otworz_dialog", lambda page, kontrolka: otwarte.append(kontrolka))
    strona = pomoce.zbuduj_strone()

    bs = ft.BottomSheet(ft.Container(padding=ft.Padding(16, 16, 16, 8), bgcolor=ft.Colors.SURFACE,
                                     content=ft.Column([ft.Text("Menu")])))
    utils.otworz_dno(strona.page, bs)
    assert otwarte == [bs] and bs.show_drag_handle is True
    assert bs.content.bgcolor is None
    assert (bs.content.padding.left, bs.content.padding.top, bs.content.padding.bottom) == (16, 0, 8)

    drugi = ft.BottomSheet(ft.Container(padding=20, content=ft.Column([ft.Text("Panel")])))
    utils.otworz_dno(strona.page, drugi)
    assert (drugi.content.padding.top, drugi.content.padding.right) == (0, 20)


def test_kazdy_arkusz_aplikacji_otwiera_otworz_dno():
    """Uchwyt i margines robi otworz_dno — arkusz otwarty inaczej zostałby kwadratowy i bez uchwytu."""
    import ast
    import pathlib

    korzen = pathlib.Path(__file__).resolve().parent.parent
    arkusze, otwarcia = 0, 0
    for plik in korzen.rglob("*.py"):
        if any(c in plik.parts for c in ("tests", ".venv", "build")):
            continue
        for wezel in ast.walk(ast.parse(plik.read_text(encoding="utf-8"))):
            if isinstance(wezel, ast.Call) and isinstance(wezel.func, ast.Attribute):
                if wezel.func.attr == "BottomSheet":
                    arkusze += 1
            if isinstance(wezel, ast.Call):
                nazwa = getattr(wezel.func, "attr", getattr(wezel.func, "id", ""))
                if nazwa == "otworz_dno":
                    otwarcia += 1
    assert arkusze and otwarcia >= arkusze


def _formularz_kosztu(monkeypatch):
    from views.formularze.inne_koszty import FormularzInneView

    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    strona = pomoce.zbuduj_strone()
    widok = FormularzInneView(strona.page, stan)
    przejscia, okna, potwierdzenia = [], [], []
    monkeypatch.setattr(utils.nawigacja, "przejdz", lambda page, trasa: przejscia.append(trasa))
    monkeypatch.setattr(utils.nawigacja, "otworz_dialog", lambda page, okno: okna.append(okno))

    async def potwierdz(czy):
        potwierdzenia.append(czy)

    widok.confirm_pop = potwierdz
    return strona, widok, przejscia, okna, potwierdzenia


def test_gest_wstecz_na_formularzu_idzie_droga_strzalki(baza, monkeypatch):
    strona, widok, przejscia, okna, potwierdzenia = _formularz_kosztu(monkeypatch)
    utils.pilnuj_gestu_wstecz(widok)
    assert widok.can_pop is False and widok.on_confirm_pop is not None

    asyncio.run(widok.on_confirm_pop(None))
    assert potwierdzenia == [False] and przejscia and not okna, "bez zmian — zwykły powrót"

    widok.e_o.value = "Myjnia"
    asyncio.run(widok.on_confirm_pop(None))
    assert potwierdzenia == [False, False] and len(okna) == 1
    assert "Niezapisane zmiany" in pomoce.napisy(okna[0])


def test_gest_wstecz_poza_formularzem_bez_zmian(baza):
    strona = pomoce.zbuduj_strone()
    widok = ft.View(route="/x", appbar=utils.zbuduj_pasek_z_powrotem(strona.page, "Ekran", "/"))
    utils.pilnuj_gestu_wstecz(widok)
    assert widok.can_pop is True and widok.on_confirm_pop is None


def test_menu_fab_to_pigulki_a_glowny_zmienia_sie_w_zamknij(baza, monkeypatch):
    db.zapisz_animacje_interfejsu(False)
    klikniete = []
    strona = pomoce.zbuduj_strone()
    menu = utils.fab_speed_dial(strona.page, [
        (ft.Icons.LOCAL_GAS_STATION, "Tankowanie", lambda e: klikniete.append("tankowanie")),
        (ft.Icons.RECEIPT_LONG, "Inny koszt", lambda e: klikniete.append("koszt")),
    ])
    pigulki, fab = menu.controls
    assert not pigulki.visible and fab.icon == ft.Icons.ADD
    assert pomoce.napisy(pigulki) == ["Tankowanie", "Inny koszt"] or set(pomoce.napisy(pigulki)) == {"Tankowanie", "Inny koszt"}
    assert all(p.height >= 48 and p.bgcolor == ft.Colors.PRIMARY_CONTAINER for p in pigulki.controls)

    fab.on_click(None)
    assert pigulki.visible and pigulki.opacity == 1 and fab.icon == ft.Icons.CLOSE
    assert isinstance(fab.shape, ft.CircleBorder)

    asyncio.run(pigulki.controls[1].on_click(None))
    assert klikniete == ["koszt"] and not pigulki.visible and fab.shape is None
