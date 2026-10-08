# GetMeAJob

Lokalna aplikacja okienkowa na macOS do zbierania i oceniania ofert pracy. Dane i CV pozostają w `~/Library/Application Support/GetMeAJob`. Ocena przez Codex korzysta z usługi modelu, więc fakty z CV i treść oferty trafiają do Codex; sam zapis aplikacji jest lokalny.

## Uruchomienie

Na tym komputerze zależności i interfejs są już zainstalowane. Otwórz dwuklikiem `Uruchom GetMeAJob.command` albo w terminalu:

```bash
./.venv/bin/python -m getmeajob
```

Pierwsza instalacja w innym środowisku:

```bash
python3 -m venv .venv
./.venv/bin/pip install -e '.[test]'
cd frontend && npm ci && npm run build && cd ..
./.venv/bin/python -m getmeajob
```

Tryb developerski bez natywnego okna: `./.venv/bin/python -m getmeajob --web`, adres `http://127.0.0.1:5757`.

## Użycie

1. W `Ustawieniach` sprawdź fakty z CV, kryteria i plik CV. Dołączone CV jest już skopiowane do lokalnego katalogu aplikacji na tym komputerze.
2. `Pobierz oferty` przeszukuje publiczne mapy RocketJobs i JustJoinIT. Możesz też dodać bezpośredni link z jednego z tych serwisów.
3. Widok `Oferty` zawiera tylko pozycje bez oceny. `Oceń nieocenione oferty` uruchamia jedną operację dla tych pozycji. Dwie oferty są analizowane równolegle, a pasek u góry pokazuje liczbę ukończonych ocen i czas pracy; błąd jednej pozycji nie zatrzymuje kolejki. Oceny nieaktualne można ponowić zbiorczo w `Do sprawdzenia`. Ocena zawiera uzasadnienie, powiązania wymagań z CV, luki oraz niewiadome. Oferty bez potwierdzonego progu pensji nie dostają automatycznie rekomendacji „aplikuj”.
4. W `Do sprawdzenia` otwórz oryginalną ofertę, przejrzyj ocenę i dopiero wtedy kliknij `Zatwierdź`. Odrzucone oferty pozostają dostępne w osobnym widoku.
5. W nowym zadaniu Codex otwartym dla tego projektu możesz poprosić: „Zaaplikuj przez przeglądarkę na zatwierdzone oferty z GetMeAJob. Użyj lokalnego MCP. Jeśli formularz wymaga informacji nieobecnych w CV, zatrzymaj się i zapytaj mnie. Zapisz potwierdzenie dopiero po rzeczywistym wysłaniu.”

Serwer MCP jest skonfigurowany w `.codex/config.toml` tego projektu. Wymaga zaufania do projektu i może wymagać otwarcia nowego zadania Codex. Polecenie `codex mcp list` powinno pokazać `getmeajob` jako włączony.

## Weryfikacja

```bash
./.venv/bin/python -m pytest -q
cd frontend && npm run build
```

Model oceny można zmienić przez `GETMEAJOB_CODEX_MODEL`; domyślnie używany jest `gpt-5.5`, dostępny na obecnym lokalnym koncie Codex. Integracja z LM Studio/Bionic, automatyczne uruchamianie sesji aplikacyjnej z okna, harmonogram synchronizacji, wykrywanie wygasłych ofert i pakiet `.app` są kolejnymi przyrostami. JustJoinIT ogranicza jedną synchronizację do 300 najświeższych kandydatów według nazw ról, aby nie obciążać serwisu.
