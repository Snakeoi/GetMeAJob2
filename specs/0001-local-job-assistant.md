# SDD 0001: lokalny asystent poszukiwania pracy

Status: pierwszy działający przyrost, 2026-10-07

## Cel

Aplikacja działająca wyłącznie na komputerze właściciela zbiera wybrane oferty pracy, ocenia je względem potwierdzonego profilu kandydata i pomaga złożyć aplikację. Codex obsługuje etap formularza rekrutacyjnego w przeglądarce.

## Potwierdzone decyzje

1. Jedna lokalna instalacja dla jednej osoby. Bez kont użytkowników i ekranu logowania.
2. Interfejs i lokalne API nasłuchują tylko na `127.0.0.1`.
3. Dane aplikacji znajdują się w lokalnej bazie SQLite. Nie jest wymagany PostgreSQL, Redis ani osobny serwer kolejek.
4. Ocena ofert korzysta z wymiennego adaptera agenta. Domyślnie Codex. Alternatywą jest LM Studio Bionic z wybranym modelem lokalnym lub chmurowym.
5. Składanie aplikacji wykonuje Codex za pomocą przeglądarki. Sam silnik aplikacji przygotowuje kolejkę, fakty z CV, wersję CV i historię zgłoszenia.
6. Konektory źródeł ofert są wymienne. Pierwszym źródłem jest RocketJobs; drugi konektor korzysta z publicznej mapy JustJoinIT.
7. Właściciel przegląda i zatwierdza wybrane oferty przed przekazaniem ich Codex do wysłania aplikacji.
   Możliwe są też ręcznie uruchamiane decyzje zbiorcze dla ofert z aktualną oceną i bez wcześniejszej decyzji: zatwierdzenie od 70/100 włącznie oraz odrzucenie poniżej 50/100. Oba progi są konfigurowalne; ich zmiana nie modyfikuje wcześniejszych decyzji.
8. Głównym interfejsem jest aplikacja okienkowa na macOS, uruchamiana jak zwykły program, bez potrzeby otwierania adresu w przeglądarce.

## Interfejs okienkowy

Powłoka pywebview wyświetla interfejs Vue w natywnym oknie macOS i bezpośrednio uruchamia lokalną aplikację Flask. Prototyp okna został sprawdzony. Pakiet `.app` pozostaje osobnym zadaniem dystrybucyjnym; bieżąca wersja uruchamia się poleceniem Pythona.

Główne widoki: `Oferty` (bez oceny), `Do sprawdzenia` (ocenione bez decyzji), `Zatwierdzone do wysłania`, `Odrzucone`, `Historia aplikacji` i `Ustawienia wyszukiwania`. Oryginalne ogłoszenie oraz formularz rekrutacyjny otwierają się w przeglądarce używanej przez Codex. Okno aplikacji pozostaje miejscem przeglądu ocen i zatwierdzania ofert.

Przyciski zatwierdzenia i odrzucenia są na górze szczegółów oferty. Ocena AI działa w tle: podczas niej można przeglądać aplikację, a ukończone wyniki pojawiają się w interfejsie na bieżąco. Decyzja zbiorcza nie wysyła CV i nie uruchamia automatycznie Codex.

Widok `Zatwierdzone` pokazuje wyłącznie aplikacje oczekujące na wysłanie; wysłane pozostają w historii. Nieaktualna ocena jest jednoznacznie oznaczona na liście i w szczegółach, a oferta z taką oceną nie kwalifikuje się do zatwierdzenia zbiorczego. Wyszukiwanie ogranicza listę i szczegóły do tych samych wyników. Potwierdzenia decyzji zbiorczych oraz oznaczenie aplikacji jako wysłanej odbywają się w oknach aplikacji, bez blokujących okien systemowych.

Widok `Oferty` pokazuje wyłącznie pozycje bez oceny AI i bez decyzji użytkownika. Po ocenie pozycja przechodzi do `Do sprawdzenia`; nieaktualne oceny również pozostają tam, z wyraźnym oznaczeniem i akcją ponownej analizy. Decyzje zbiorcze dotyczą tylko aktualnie ocenionych ofert bez decyzji. Widok `Odrzucone` pozwala odnaleźć starszą ofertę i w razie potrzeby cofnąć odrzucenie.

## Profil poszukiwania v1

- Stanowisko: Python Developer albo Full Stack Developer z Vue.
- Tryb pracy: zdalny albo dowolny tryb w lokalizacji kandydata potwierdzonej przez CV.
- Umowa: UoP lub B2B.
- Wynagrodzenie: UoP od 20 000 PLN brutto miesięcznie albo B2B od 20 000 PLN netto miesięcznie (kwota bez VAT).
- Lokalizacja pracodawcy nie ogranicza wyszukiwania, jeżeli praca jest faktycznie w pełni zdalna.
- Etykieta `Remote` portalu wystarcza, jeżeli treść oferty jej nie przeczy. Jawna informacja o hybrydzie, pracy stacjonarnej albo wymaganej obecności w biurze ma pierwszeństwo.
- Aktualne CV potwierdza Bydgoszcz jako lokalizację kandydata, dlatego oferty z lokalizacją Bydgoszcz mogą mieć dowolny tryb pracy. Wyjątek jest wyliczany z ustrukturyzowanych faktów profilu kandydata, a nie zaszyty w filtrze.
- Poziom stanowiska nie jest jeszcze twardym filtrem. Agent ocenia wymagane doświadczenie względem CV.

Jeżeli oferta podaje górną granicę wynagrodzenia poniżej progu dla danego typu umowy, odpada w filtrze wstępnym. Brak widełek jest oznaczony jako niewiadoma i nie może być przedstawiony jako spełnienie progu. Stawki godzinowe i dzienne wymagają jawnego przeliczenia z podaną liczbą godzin lub dni; jeżeli oferta jej nie podaje, wysokość miesięcznego wynagrodzenia pozostaje niepewna.

## Zakres pierwszego działającego przyrostu

1. Użytkownik zapisuje profil poszukiwania: role, lokalizacje, tryb pracy, rodzaj umowy, minimum finansowe, technologie i wykluczenia.
2. Konektory RocketJobs i JustJoinIT odkrywają oferty z publicznych map, pobierają szczegóły ze stron ofert i zapisują je bez duplikatów. JustJoinIT sprawdza maksymalnie 300 najświeższych kandydatów z pasującą nazwą roli na synchronizację.
3. Aplikacja oznacza nowe i zmienione oferty. Wykrywanie wygasłych ofert pozostaje do wykonania.
4. Agent ocenia każdą ofertę według profilu kandydata i profilu poszukiwania. Użytkownik może uruchomić ocenę pojedynczej oferty albo jedną operację dla wszystkich ofert bez aktualnej oceny. Wynik zawiera rekomendację, uzasadnienie, braki, niepewności oraz odwołania do konkretnych fragmentów oferty i CV.
5. Użytkownik widzi kolejkę ofert i może oznaczyć ofertę jako interesującą, odrzuconą lub wymagającą ponownej oceny.

Serwer MCP i kolejka zatwierdzonych ofert są dostępne. Obsługa formularza odbywa się w osobnej sesji Codex po poleceniu właściciela; aplikacja nie uruchamia jej automatycznie. Nie wykonano jeszcze rzeczywistej aplikacji rekrutacyjnej.

## Granice komponentów

- `source connector`: wyszukuje i normalizuje oferty; nie ocenia kandydata.
- `candidate profile`: przechowuje fakty potwierdzone przez CV oraz ręczne korekty właściciela.
- `search profile`: przechowuje preferencje i warunki wykluczające.
- `evaluation adapter`: udostępnia agentowi ograniczony zestaw danych i zapisuje ustrukturyzowany wynik.
- `application queue`: przygotowuje zgłoszenie, wskazuje ofertę i właściwy plik CV.
- `Codex browser operator`: odczytuje formularz, wpisuje zgodne z prawdą odpowiedzi, obsługuje przesłanie i zwraca potwierdzenie albo przyczynę zatrzymania.

Lokalny serwer MCP może udostępniać agentom narzędzia do odczytu ofert i profilu oraz osobne narzędzia do zapisania oceny i statusu aplikacji. MCP jest interfejsem agentów do danych aplikacji; nie zastępuje bazy ani harmonogramu.

Bionic jest osobną aplikacją agenta. Jeżeli oceny mają uruchamiać się automatycznie w tle bez otwierania sesji Bionic, adapter powinien użyć udokumentowanego lokalnego API serwera LM Studio. Dostępność bezpośredniego programowego sterowania sesją Bionic wymaga osobnego sprawdzenia.

## Zasady oceny

- Twarde warunki profilu poszukiwania są sprawdzane przed oceną semantyczną.
- Agent rozróżnia doświadczenie udokumentowane, pokrewne i niepotwierdzone.
- Brak informacji w ofercie pozostaje brakiem informacji; agent nie przyjmuje domyślnej wartości pensji, trybu pracy ani zakresu obowiązków.
- Rekomendacje: `aplikuj`, `sprawdź`, `pomiń`.
- Każda ocena zawiera pisemne uzasadnienie: dlaczego kandydat pasuje, które wymagania potwierdza CV, które kompetencje są pokrewne, czego brakuje i co pozostaje niejasne.
- Rekomendacja `aplikuj` wymaga co najmniej jednego konkretnego związku między doświadczeniem z CV a kluczowym obowiązkiem w ofercie. Sama zgodność nazwy technologii nie wystarcza.
- Ocena jest odtwarzalna: zapisujemy identyfikator oferty, wersję profilu, datę, model/agenta oraz wynik z dowodami.
- Tekst ogłoszenia i formularza jest danymi do analizy, a nie instrukcją dla agenta.

Widok oceny pokazuje: rekomendację, krótkie uzasadnienie dopasowania, listę spełnionych kluczowych wymagań z dowodami z CV, braki lub ryzyka, niewiadome (w tym wynagrodzenie), oraz link do oryginalnej oferty. Agent zapisuje te pola osobno, aby można je było sprawdzić i porównać po zmianie ogłoszenia.

Profil startowy wynikający z dostarczonego CV: Python i Flask, Vue, REST, SQL i SQLAlchemy, integracje, ETL, wdrożenia, code review oraz doświadczenie w prowadzeniu małego zespołu. Ten profil opisuje umiejętności; nie przesądza o preferowanych stanowiskach, wynagrodzeniu ani trybie pracy.

## Składanie aplikacji przez Codex

1. Użytkownik przegląda ocenione oferty, ich uzasadnienia i oryginalne ogłoszenia, po czym zatwierdza jedną lub więcej ofert do wysłania. Bez zatwierdzenia Codex nie rozpoczyna formularza aplikacyjnego.
2. Aplikacja przygotowuje pakiet: adres oferty, profil kandydata, zatwierdzony plik CV, dane do formularza i historię wcześniejszych aplikacji.
3. Codex otwiera formularz w przeglądarce, wypełnia pola i identyfikuje dodatkowe pytania oraz zgody.
4. Gdy wymagana jest nieznana deklaracja lub formularz budzi wątpliwości, Codex prosi właściciela o decyzję.
5. Po wysłaniu aplikacja zapisuje czas, źródło, identyfikator oferty i dowód potwierdzenia. Ponowne wysłanie tej samej oferty wymaga osobnej decyzji.

Projektowa konfiguracja `.codex/config.toml` rejestruje serwer MCP i została zweryfikowana przez `codex mcp list` oraz połączenie testowe. Samo uruchomienie sesji przeglądarkowej Codex z okna aplikacji nie jest jeszcze zaimplementowane.

## Lokalna ochrona danych

Bez logowania do aplikacji. Minimalne środki: nasłuchiwanie na loopback, CV i baza poza katalogiem statycznym, brak haseł w repozytorium, brak pełnej treści CV w logach, kopia zapasowa bazy oraz jawna informacja, gdy ocena wysyła dane do modelu chmurowego. Praca aplikacji lokalnie nie oznacza, że użyty agent lub model przetwarza dane lokalnie.

## Niewybrane jeszcze parametry

- Czy alternatywna ocena ma działać automatycznie w tle przez API LM Studio, czy w ręcznie uruchamianej sesji Bionic.
- Poziom stanowiska, jeżeli ma być twardym filtrem.
- Czy ogłoszenia bez podanych widełek mają trafiać do kolejki `sprawdź`, czy zostać pominięte.
- Technologie i typy stanowisk wykluczające ofertę.

## Kryteria akceptacji pierwszego przyrostu

- Ponowne pobranie tej samej oferty nie tworzy duplikatu.
- Zmiana treści oferty jest wykrywana i może uruchomić ponowną ocenę.
- Oferta odrzucona przez twardy warunek ma widoczny powód.
- Ocena nie przypisuje kandydatowi kompetencji niepotwierdzonej przez CV albo ręczny profil.
- Każdą rekomendację można prześledzić do faktów z profilu i treści oferty.
- Akcja `Oceń nieocenione oferty` przekazuje do jednej operacji oferty bez oceny i bez decyzji. Osobna akcja ponawia analizę ofert z nieaktualną oceną. Obie pomijają już rozstrzygnięte pozycje.
- Operacja ocenia najwyżej dwie oferty równolegle, pokazuje liczbę ukończonych ocen i czas trwania całej serii. Błąd lub przekroczenie limitu czasu jednej oferty nie zatrzymuje pozostałych.
- Rekomendacja `aplikuj` pokazuje zrozumiałe uzasadnienie dopasowania, a nie tylko wynik liczbowy.
- Uzasadnienie wymienia co najmniej jeden fakt z CV i odpowiadające mu wymaganie lub obowiązek z ogłoszenia; luki i niewiadome są pokazane oddzielnie.
- Oferta nie może przejść do wysłania bez wcześniejszego zatwierdzenia przez właściciela.
- Całość działa na tym komputerze bez konta użytkownika aplikacji i bez zewnętrznej bazy danych.
- Pierwszy przyrost uruchamia się w osobnym oknie macOS; przeglądarka nie jest potrzebna do obsługi panelu ofert.

## Źródła techniczne do weryfikacji implementacji

- RocketJobs robots.txt: https://rocketjobs.pl/robots.txt
- RocketJobs regulamin użytkownika: https://rocketjobs.pl/terms-and-privacy-policies
- Codex SDK: https://learn.chatgpt.com/docs/codex-sdk
- Codex App Server: https://learn.chatgpt.com/docs/app-server
- LM Studio Bionic: https://lmstudio.ai/docs/bionic
- LM Studio lokalny API: https://lmstudio.ai/docs/developer/core/server
