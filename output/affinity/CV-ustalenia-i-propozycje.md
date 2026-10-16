# CV — ustalenia i propozycje treści

Dokument roboczy na podstawie rozmowy z 12 października 2026 r. Nie zastępuje zatwierdzonego CV ani profilu kandydata w bazie GetMeAJob.

## Potwierdzone przez Janusza

- Automatyczne testy backendu w pytest: endpointy API, operacje bazodanowe, fixtures i mocki. UI testowane głównie ręcznie. Doświadczenie z testami i bazami w Nordea, Otinus i Automatykon.
- Projektowanie całych relacyjnych baz danych; migracje Alembic i ręczne skrypty SQL. Ograniczanie zbędnych odczytów oraz stosowanie widoków SQL zamiast skomplikowanych zapytań ORM. Bez potwierdzonych pomiarów przyspieszenia.
- Automatyzacja aktualizacji aplikacji skryptami Bash na Linuksie, przede wszystkim w Nordea: kopie baz, pobieranie kodu z Git, migracje i aktualizacja frontendu. Sposób uruchamiania niepotwierdzony; nie nazywać pełnym CI/CD.
- Microsoft SQL Server używany w Nordea; zakres i okres stosowania nieustalone.
- Vue 3: Options API i Composition API.
- Django i FastAPI: podstawowa znajomość. Brak praktycznego użycia Pydantic i praktycznie brak doświadczenia chmurowego.
- Selenium: deklarowana podstawowa znajomość; zastosowania nieustalone.
- Sellos: samodzielne stworzenie całej aplikacji na podstawie wymagań zarządu i sugestii użytkowników; utrzymanie aplikacji oraz zgodności katalogu, cen i parametrów maszyn z ofertą firmy.
- Otinus: wdrożenie programisty przejmującego obowiązki.
- Nordea: odpowiedzialność za aplikację dostawcy zewnętrznego oraz rozwój innych aplikacji wewnętrznych. W CV pomijać nazwy, obszar zastosowania i szczegóły systemów objętych poufnością.
- Bardzo częsta komunikacja po angielsku w pracy. Nie zmieniać automatycznie deklaracji poziomu na C1.

## Proponowane punkty do CV

- Tworzenie automatycznych testów endpointów API i operacji bazodanowych w pytest z wykorzystaniem fixtures i mocków; manualne testowanie interfejsów użytkownika.
- Projektowanie relacyjnych baz danych i zarządzanie migracjami z wykorzystaniem Alembic i skryptów SQL.
- Optymalizacja dostępu do danych poprzez ograniczanie zbędnych odczytów i wykorzystanie widoków SQL zamiast złożonych zapytań ORM.
- Automatyzacja wdrożeń aplikacji skryptami Bash w środowisku Linux: kopie zapasowe baz, pobieranie kodu z Git, migracje i aktualizacja frontendu.
- Praca z Microsoft SQL Server w Nordea.
- Rozwój interfejsów w Vue 3 z wykorzystaniem Options API i Composition API.
- Regularna komunikacja zawodowa w języku angielskim.

### Sellos — Otinus

Samodzielne zaprojektowanie, stworzenie i wdrożenie aplikacji do przygotowywania ofert handlowych, na podstawie wymagań zarządu i informacji zwrotnych użytkowników. Odpowiedzialność za rozwój i utrzymanie rozwiązania oraz aktualność katalogu maszyn, parametrów technicznych i danych cenowych.

### GetMeAJob — projekt własny

Rozwój lokalnego asystenta poszukiwania pracy w Pythonie/Flask, Vue 3 i SQLite, z wykorzystaniem AI oraz podejścia Spec-Driven Development (SDD). Projekt obejmuje pobieranie ofert z trzech serwisów, ocenę dopasowania ofert do profilu kandydata przez AI i serwer MCP udostępniający dane agentowi. Praca na podstawie specyfikacji i kryteriów akceptacji; testy automatyczne obejmujące integracje, API i reguły biznesowe.

Potwierdzenie w repozytorium: specs/0001-local-job-assistant.md, getmeajob/evaluation.py, getmeajob/mcp_server.py, tests/, pyproject.toml i frontend/package.json. Projekt jest rozwijany przy wsparciu AI; nie przypisywać ręcznego napisania całego kodu ani doświadczenia komercyjnego z tego projektu. Nie wywodzić z niego doświadczenia RAG, trenowania modeli ani uruchomionej integracji z lokalnym LLM.

## Do doprecyzowania

- Docker: konkretne zastosowanie, środowisko zawodowe lub prywatne.
- Selenium: konkretne zastosowanie, środowisko zawodowe lub prywatne.
- Czy skrypty Bash uruchamiano ręcznie, czy automatycznie.
- Ponowne potwierdzenie liczb Sellos: ponad 13 000 ofert i około 2 minuty na 30-stronicowy PDF. Występują w dotychczasowym CV, ale ostatnia numeracja odpowiedzi jest niejednoznaczna.
- Dokładny zakres pracy w Microsoft SQL Server — nie przypisywać administracji serwerem ani zaawansowanego T-SQL bez potwierdzenia.
