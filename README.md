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

1. Przy pierwszym uruchomieniu otwórz `Ustawienia`: dodaj własne CV, wyciągnij i sprawdź fakty, a następnie zapisz stanowiska, dopuszczalne tryby i lokalizacje pracy, formy zatrudnienia oraz minimalne wynagrodzenie. Bez stanowisk aplikacja nie pobierze ofert; bez faktów z CV nie uruchomi oceny. Na tym komputerze wcześniej zapisane CV i ustawienia pozostają dostępne. Każda osobna instalacja zaczyna z pustym profilem kandydata i poszukiwania.
2. `Pobierz oferty` otwiera wybór serwisów: RocketJobs, JustJoinIT, Pracuj.pl, No Fluff Jobs, Bulldogjob i SOLID.Jobs. Zaznacz co najmniej jeden; synchronizacja przeszuka tylko wybrane. Możesz też dodać bezpośredni link z jednego z tych serwisów. Pracuj.pl czasem chroni zwykłe żądania przez Cloudflare; wtedy aplikacja korzysta z tekstowego podglądu publicznej strony, przekazując wyłącznie URL oferty — bez CV i danych kandydata.
3. Widok `Oferty` zawiera tylko pozycje bez oceny. `Oceń nieocenione oferty` uruchamia jedną operację dla tych pozycji. Dwie oferty są analizowane równolegle, a pasek u góry pokazuje liczbę ukończonych ocen i czas pracy; błąd jednej pozycji nie zatrzymuje kolejki. Oceny nieaktualne można ponowić zbiorczo w `Do sprawdzenia`. Ocena zawiera uzasadnienie, powiązania wymagań z CV, luki oraz niewiadome. Gdy ustawisz próg wynagrodzenia, oferta bez potwierdzonej kwoty nie dostanie automatycznie rekomendacji „aplikuj”.
4. W `Do sprawdzenia` otwórz oryginalną ofertę, przejrzyj ocenę i dopiero wtedy kliknij `Zatwierdź`. Odrzucone oferty pozostają dostępne w osobnym widoku.
5. W nowym zadaniu Codex otwartym dla tego projektu możesz poprosić: „Zaaplikuj przez przeglądarkę na zatwierdzone oferty z GetMeAJob. Użyj lokalnego MCP. Jeśli formularz wymaga informacji nieobecnych w CV, zatrzymaj się i zapytaj mnie. Oznacz jako wysłane dopiero po rzeczywistym wysłaniu.” Notatka z potwierdzeniem jest opcjonalna.

Serwer MCP jest skonfigurowany w `.codex/config.toml` tego projektu. Wymaga zaufania do projektu i może wymagać otwarcia nowego zadania Codex. Polecenie `codex mcp list` powinno pokazać `getmeajob` jako włączony.

## Weryfikacja

```bash
./.venv/bin/python -m pytest -q
cd frontend && npm run build
```

Aplikacja preferuje Codex CLI dołączony do ChatGPT lub Codex w `/Applications`, a następnie polecenie `codex` z PATH. Własną ścieżkę można ustawić przez `GETMEAJOB_CODEX_EXECUTABLE`.

Model oceny można zmienić przez `GETMEAJOB_CODEX_MODEL`; bez tej zmiennej model wybiera Codex CLI według swojego domyślnego ustawienia (bez wczytywania konfiguracji użytkownika). Integracja z LM Studio/Bionic, automatyczne uruchamianie sesji aplikacyjnej z okna, harmonogram synchronizacji, wykrywanie wygasłych ofert i pakiet `.app` są kolejnymi przyrostami. JustJoinIT po jednym kliknięciu pobiera wszystkie pasujące oferty w kolejnych partiach do 300, z opóźnieniem między żądaniami. Trwale zapisany postęp pozwala wznowić pobieranie po przerwaniu. Pracuj.pl pobiera domyślnie do 80 kandydatów z dwóch stron wyników, aby nie obciążać serwisów.

### No Fluff Jobs

Konektor czyta publiczne strony HTML i osadzone w nich dane ofert, respektując robots.txt. Nie korzysta z prywatnego API ani logowania. Wyszukiwanie używa stanowisk z ustawień (kwalifikatory takie jak „z Vue” sprawdza wspólny filtr po pobraniu szczegółów). Domyślne limity to 3 strony i 60 kandydatów na stanowisko, z przerwą 0,5 s między żądaniami. Raport synchronizacji zawiera liczbę stron, kandydatów i błędów szczegółów. Oferty powtarzające się między stronami i frazami są pobierane raz.

Stawki godzinowe i dzienne pozostają w oryginalnej jednostce i walucie. Przy kilku formach zatrudnienia osobne widełki są zachowane w opisie; wspólne pole wynagrodzenia pozostaje nieokreślone, ponieważ model przechowuje jedną stawkę. Nie jest to pełne pokrycie wszystkich wyników portalu ani deduplikacja między różnymi portalami.

### Bulldogjob i SOLID.Jobs

Oba konektory korzystają z publicznych map ofert, sprawdzają robots.txt i pobierają maksymalnie 150 najnowszych kandydatów pasujących nazwą roli. Szczegóły pochodzą z publicznych stron ofert. Konektor Bulldogjob używa dostępnej oficjalnej domeny `bulldogjob.com`; linki z `bulldogjob.pl` przy imporcie są zamieniane na odpowiadający im adres `.com`. Raport pokazuje liczbę pozycji na mapie, kandydatów i błędów szczegółów. Stawki o różnych umowach pozostają osobno w opisie, bez łączenia w jedną kwotę.

theprotocol.it nie jest jeszcze dostępny jako źródło synchronizacji: mapa ofert i strony ogłoszeń zwracają ochronę Cloudflare dla lokalnego klienta HTTP, również przez publiczny podgląd tekstowy. Zarejestrowanie takiego konektora dawałoby obecnie wyłącznie błędy synchronizacji.
