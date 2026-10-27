from scraper.consultantplus.text import clean_decision_text


def test_removes_summary_controls_and_document_counter():
    source = ('Краткий пересказ\nДокумент: 1/19\nОПРЕДЕЛЕНИЕ\n'
              'См. также:Краткий пересказ\nТекст решения\n'
              'Председатель\nВ.Д.ЗОРЬКИН\nСм. также: Краткий пересказ')
    assert clean_decision_text(source) == 'ОПРЕДЕЛЕНИЕ\n\nТекст решения\nПредседатель\nВ.Д.ЗОРЬКИН'


def test_cleanup_handles_spaces_case_and_windows_newlines():
    source = '\tКРАТКИЙ ПЕРЕСКАЗ\r\nДокумент:  12 / 190\r\nРЕШЕНИЕ'
    assert clean_decision_text(source) == 'РЕШЕНИЕ'


def test_preserves_numbers_and_summary_mentions_in_actual_decision():
    source = ('Доля истца составляет 1/19.\n'
              '1/19\n'
              'Документ: 1/19 от 25.07.2002\n'
              'Истец представил краткий пересказ обстоятельств дела.\n'
              'См. также: решение областного суда.')
    assert clean_decision_text(source) == source
