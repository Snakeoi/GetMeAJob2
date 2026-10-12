<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  ArrowDownToLine, ArrowRight, BadgeCheck, BriefcaseBusiness, Check, ChevronRight,
  CircleAlert, ExternalLink, FolderCheck, LayoutDashboard,
  Link2, LoaderCircle, MapPin, RotateCw, Search, Settings2,
  Sparkles, ThumbsDown, Wallet, X,
} from 'lucide-vue-next'

const section = ref('overview')
const offers = ref([])
const applications = ref([])
const selectedId = ref(null)
const token = ref('')
const searchProfile = ref(null)
const decisionProfile = ref(null)
const candidateProfile = ref(null)
const resumeName = ref(null)
const operation = ref({ status: 'idle' })
const lastSyncReport = ref(null)
const availableSources = ref([])
const selectedSyncSourceIds = ref([])
const showSync = ref(false)
const syncStarting = ref(false)
const search = ref('')
const importUrl = ref('')
const showImport = ref(false)
const pendingBulkDecision = ref(null)
const bulkSaving = ref(false)
const pendingSubmission = ref(null)
const submissionConfirmation = ref('')
const submissionSaving = ref(false)
const showDatabaseReset = ref(false)
const databaseResetConfirmation = ref('')
const databaseResetSaving = ref(false)
const notice = ref('')
const error = ref('')
const saving = ref(false)
const excludedText = ref('')
const candidateFactsText = ref('')
const clock = ref(Date.now())
let poller = null
let clockTimer = null
let polling = false

const nav = [
  { id: 'overview', label: 'Przegląd', icon: LayoutDashboard },
  { id: 'offers', label: 'Oferty', icon: BriefcaseBusiness },
  { id: 'review', label: 'Do sprawdzenia', icon: Sparkles },
  { id: 'approved', label: 'Zatwierdzone', icon: FolderCheck },
  { id: 'rejected', label: 'Odrzucone', icon: ThumbsDown },
  { id: 'submitted', label: 'Wysłane', icon: BadgeCheck },
  { id: 'settings', label: 'Ustawienia', icon: Settings2 },
]

const selected = computed(() => visibleOffers.value.find((item) => item.id === selectedId.value) || null)
const selectedApplication = computed(() => applications.value.find((item) => item.offer_id === selectedId.value) || null)
const pendingApprovedIds = computed(() => new Set(applications.value.filter((item) => item.status === 'approved').map((item) => item.offer_id)))
const submittedOfferIds = computed(() => new Set(applications.value.filter((item) => item.status === 'submitted').map((item) => item.offer_id)))
const submittedApplications = computed(() => applications.value.filter((item) => item.status === 'submitted'))
const unevaluatedOfferIds = computed(() => offers.value
  .filter((item) => item.decision === 'none' && !item.evaluation)
  .map((item) => item.id))
const staleOfferIds = computed(() => offers.value
  .filter((item) => item.evaluation && item.evaluation_stale && !submittedOfferIds.value.has(item.id))
  .map((item) => item.id))
const counters = computed(() => ({
  all: offers.value.length,
  rejected: offers.value.filter((item) => item.decision === 'rejected').length,
  unrated: unevaluatedOfferIds.value.length,
  stale: staleOfferIds.value.length,
  review: offers.value.filter((item) => item.decision === 'none' && item.evaluation).length,
  recommended: offers.value.filter((item) => !item.evaluation_stale && item.evaluation?.recommendation === 'aplikuj' && item.decision === 'none').length,
  approved: offers.value.filter((item) => pendingApprovedIds.value.has(item.id)).length,
  submitted: applications.value.filter((item) => item.status === 'submitted').length,
}))
const bulkEligible = computed(() => {
  const pending = offers.value.filter((item) => item.decision === 'none' && item.evaluation && !item.evaluation_stale)
  return {
    approved: pending.filter((item) => item.evaluation.score >= decisionProfile.value?.approve_min_score).length,
    rejected: pending.filter((item) => item.evaluation.score < decisionProfile.value?.reject_below_score).length,
  }
})
const visibleOffers = computed(() => {
  let result = offers.value
  if (section.value === 'offers') result = result.filter((item) => item.decision === 'none' && !item.evaluation)
  if (section.value === 'review') result = result.filter((item) => item.decision === 'none' && item.evaluation)
  if (section.value === 'approved') result = result.filter((item) => pendingApprovedIds.value.has(item.id))
  if (section.value === 'rejected') result = result.filter((item) => item.decision === 'rejected')
  const query = search.value.trim().toLowerCase()
  if (query) result = result.filter((item) => `${item.title} ${item.company} ${item.description}`.toLowerCase().includes(query))
  return result
})
watch(visibleOffers, (items) => {
  if (!items.some((item) => item.id === selectedId.value)) selectedId.value = items[0]?.id || null
})
const activeTitle = computed(() => nav.find((item) => item.id === section.value)?.label || 'Oferty')
const emptyListMessage = computed(() => {
  if (search.value.trim()) return 'Brak wyników wyszukiwania.'
  if (section.value === 'offers') return 'Brak nieocenionych ofert.'
  if (section.value === 'review') return 'Brak ofert do sprawdzenia.'
  if (section.value === 'approved') return 'Brak zatwierdzonych ofert.'
  if (section.value === 'rejected') return 'Brak odrzuconych ofert.'
  return 'Brak ofert.'
})
const operationElapsed = computed(() => {
  if (operation.value.status !== 'running' || !operation.value.started_at) return ''
  const seconds = Math.max(0, Math.floor((clock.value - Date.parse(operation.value.started_at)) / 1000))
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${String(seconds % 60).padStart(2, '0')}`
})

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) }
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json'
  if (options.method && options.method !== 'GET') headers['X-Local-Token'] = token.value
  const response = await fetch(path, { ...options, headers })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.error || `Błąd ${response.status}`)
  return data
}

async function boot() {
  try {
    const data = await api('/api/bootstrap')
    token.value = data.token
    searchProfile.value = data.search_profile
    decisionProfile.value = data.decision_profile
    candidateProfile.value = data.candidate_profile
    resumeName.value = data.resume_name
    operation.value = data.operation
    lastSyncReport.value = data.last_sync_report
    availableSources.value = data.sources || []
    selectedSyncSourceIds.value = availableSources.value.map((source) => source.id)
    excludedText.value = (data.search_profile.excluded_terms || []).join(', ')
    candidateFactsText.value = data.candidate_profile.facts.map((fact) => fact.text).join('\n')
    await refresh()
  } catch (exc) {
    error.value = exc.message
  }
  poller = setInterval(pollOperation, 2000)
}

async function refresh() {
  const [newOffers, newApplications] = await Promise.all([api('/api/offers'), api('/api/applications')])
  offers.value = newOffers
  applications.value = newApplications
  if (!newOffers.some((item) => item.id === selectedId.value)) selectedId.value = newOffers[0]?.id || null
}

async function pollOperation() {
  if (operation.value.status !== 'running' || polling) return
  polling = true
  try {
    const next = await api('/api/operation')
    const progressChanged = next.current !== operation.value.current
    operation.value = next
    if (progressChanged || next.status !== 'running') await refresh()
    if (next.status === 'done') {
      if (next.kind === 'sync') lastSyncReport.value = next.result
      notice.value = next.kind === 'sync' ? `Pobieranie zakończone: ${next.result?.new ?? 0} nowych ofert.` : 'Ocena ofert zakończona. Wyniki są w „Do sprawdzenia”.'
      if (next.result?.errors?.length) error.value = `${next.result.errors.length} ocen nie powiodło się. ${next.result.errors[0].error}`
    } else if (next.status === 'error') {
      error.value = next.message
      if (next.kind === 'sync') lastSyncReport.value = (await api('/api/bootstrap')).last_sync_report
    }
  } catch (exc) {
    error.value = exc.message
  } finally { polling = false }
}

function openSyncDialog() {
  error.value = ''
  showSync.value = true
}

async function startSync() {
  if (!selectedSyncSourceIds.value.length || syncStarting.value) return
  try {
    syncStarting.value = true
    error.value = ''
    await api('/api/sync', { method: 'POST', body: JSON.stringify({ sources: selectedSyncSourceIds.value }) })
    showSync.value = false
    const now = new Date().toISOString()
    operation.value = { kind: 'sync', status: 'running', message: 'Szukam ofert…', current: 0, total: 0, started_at: now, updated_at: now }
  } catch (exc) { error.value = exc.message }
  finally { syncStarting.value = false }
}

async function startEvaluation(ids) {
  if (!ids.length) return
  try {
    error.value = ''
    await api('/api/evaluate', { method: 'POST', body: JSON.stringify({ ids }) })
    const now = new Date().toISOString()
    operation.value = { kind: 'evaluate', status: 'running', message: `Ukończono 0/${ids.length}. Uruchamiam ocenę…`, current: 0, total: ids.length, started_at: now, updated_at: now }
  } catch (exc) { error.value = exc.message }
}

function startUnevaluatedEvaluation() {
  return startEvaluation(unevaluatedOfferIds.value)
}

function startStaleEvaluation() {
  return startEvaluation(staleOfferIds.value)
}

async function importOffer() {
  if (!importUrl.value.trim()) return
  try {
    saving.value = true
    error.value = ''
    const result = await api('/api/offers/import', { method: 'POST', body: JSON.stringify({ url: importUrl.value.trim() }) })
    await refresh()
    openOffer(result.offer)
    showImport.value = false
    importUrl.value = ''
    notice.value = result.warning ? `Oferta dodana. Uwaga: ${result.warning}` : 'Oferta dodana.'
  } catch (exc) { error.value = exc.message }
  finally { saving.value = false }
}

async function decide(decision) {
  if (!selected.value) return
  try {
    error.value = ''
    await api(`/api/offers/${selected.value.id}/decision`, { method: 'POST', body: JSON.stringify({ decision }) })
    await refresh()
    notice.value = decision === 'approved' ? 'Oferta zatwierdzona do wysłania przez Codex.' : decision === 'rejected' ? 'Oferta odrzucona.' : 'Decyzja cofnięta.'
  } catch (exc) { error.value = exc.message }
}

async function bulkDecide(decision) {
  try {
    error.value = ''
    await refresh()
    const count = bulkEligible.value[decision]
    if (!count) {
      notice.value = 'Brak ofert spełniających ten próg.'
      return
    }
    const threshold = decision === 'approved' ? decisionProfile.value.approve_min_score : decisionProfile.value.reject_below_score
    pendingBulkDecision.value = { decision, count, threshold }
  } catch (exc) { error.value = exc.message }
}

async function confirmBulkDecision() {
  const decision = pendingBulkDecision.value?.decision
  if (!decision) return
  try {
    bulkSaving.value = true
    error.value = ''
    const result = await api('/api/offers/bulk-decision', { method: 'POST', body: JSON.stringify({ decision }) })
    await refresh()
    pendingBulkDecision.value = null
    notice.value = !result.count ? 'Brak nowych ofert spełniających ten próg.' : decision === 'approved'
      ? `Zatwierdzono ${result.count} ${offerCountNoun(result.count, true)}. CV nie zostało wysłane.`
      : `Odrzucono ${result.count} ${offerCountNoun(result.count, true)}.`
  } catch (exc) { error.value = exc.message }
  finally { bulkSaving.value = false }
}

async function saveSettings() {
  try {
    saving.value = true
    error.value = ''
    const approve = Number(decisionProfile.value.approve_min_score)
    const reject = Number(decisionProfile.value.reject_below_score)
    if (!Number.isInteger(approve) || !Number.isInteger(reject) || reject < 0 || reject > approve || approve > 100) {
      throw new Error('Podaj całkowite progi 0–100; próg odrzucenia nie może przekraczać progu zatwierdzenia.')
    }
    decisionProfile.value = await api('/api/decision-profile', { method: 'PUT', body: JSON.stringify({ approve_min_score: approve, reject_below_score: reject }) })
    const profile = { ...searchProfile.value, excluded_terms: excludedText.value.split(',').map((x) => x.trim()).filter(Boolean) }
    profile.minimum_uop_gross_pln_month = Number(profile.minimum_uop_gross_pln_month)
    profile.minimum_b2b_net_pln_month = Number(profile.minimum_b2b_net_pln_month)
    searchProfile.value = await api('/api/search-profile', { method: 'PUT', body: JSON.stringify(profile) })
    const factLines = candidateFactsText.value.split('\n').map((x) => x.trim()).filter(Boolean)
    candidateProfile.value = await api('/api/candidate-profile', {
      method: 'PUT',
      body: JSON.stringify({
        ...candidateProfile.value,
        facts: factLines.map((text, index) => ({
          ...(candidateProfile.value.facts[index] || {}),
          id: candidateProfile.value.facts[index]?.id || `manual-${index + 1}`,
          text,
        })),
      }),
    })
    await refresh()
    notice.value = 'Ustawienia zapisane. Po zmianie profilu lub CV poprzednie oceny warto odświeżyć.'
  } catch (exc) { error.value = exc.message }
  finally { saving.value = false }
}

async function uploadResume(event) {
  const file = event.target.files?.[0]
  if (!file) return
  try {
    const body = new FormData()
    body.append('file', file)
    const result = await api('/api/resume', { method: 'POST', body })
    resumeName.value = result.resume_name
    notice.value = 'CV zapisane lokalnie.'
  } catch (exc) { error.value = exc.message }
}

function markSubmitted(application) {
  error.value = ''
  submissionConfirmation.value = ''
  pendingSubmission.value = application
}

async function confirmSubmission() {
  const confirmation = submissionConfirmation.value.trim()
  try {
    submissionSaving.value = true
    error.value = ''
    await api(`/api/applications/${pendingSubmission.value.offer_id}/submitted`, { method: 'POST', body: JSON.stringify({ confirmation }) })
    await refresh()
    pendingSubmission.value = null
    notice.value = 'Aplikacja została przeniesiona do „Wysłanych”.'
  } catch (exc) { error.value = exc.message }
  finally { submissionSaving.value = false }
}

async function resetDatabase() {
  if (databaseResetConfirmation.value !== 'USUŃ WSZYSTKO') return
  try {
    databaseResetSaving.value = true
    error.value = ''
    const result = await api('/api/database/reset', {
      method: 'POST',
      body: JSON.stringify({ confirmation: databaseResetConfirmation.value }),
    })
    showDatabaseReset.value = false
    databaseResetConfirmation.value = ''
    section.value = 'overview'
    selectedId.value = null
    await bootAfterReset()
    notice.value = `Baza została wyczyszczona. Kopia: ${result.backup_name}`
  } catch (exc) { error.value = exc.message }
  finally { databaseResetSaving.value = false }
}

async function bootAfterReset() {
  const data = await api('/api/bootstrap')
  searchProfile.value = data.search_profile
  decisionProfile.value = data.decision_profile
  candidateProfile.value = data.candidate_profile
  resumeName.value = data.resume_name
  lastSyncReport.value = data.last_sync_report
  excludedText.value = (data.search_profile.excluded_terms || []).join(', ')
  candidateFactsText.value = data.candidate_profile.facts.map((fact) => fact.text).join('\n')
  await refresh()
}

function pickSection(id) {
  section.value = id
  search.value = ''
  const first = visibleOffers.value[0]
  selectedId.value = first?.id || null
}

function openOffer(offer) {
  section.value = submittedOfferIds.value.has(offer.id) ? 'submitted'
    : offer.decision === 'rejected' ? 'rejected'
      : pendingApprovedIds.value.has(offer.id) ? 'approved'
        : offer.evaluation ? 'review' : 'offers'
  search.value = ''
  selectedId.value = offer.id
}

function formatMoney(amount) {
  return new Intl.NumberFormat('pl-PL', { maximumFractionDigits: 0 }).format(amount)
}

function offerCountNoun(count, accusative = false) {
  if (count === 1) return accusative ? 'ofertę' : 'oferta'
  const lastTwo = count % 100
  return count % 10 >= 2 && count % 10 <= 4 && (lastTwo < 12 || lastTwo > 14) ? 'oferty' : 'ofert'
}

function salaryText(salary) {
  if (!salary?.minimum && !salary?.maximum) return 'Wynagrodzenie nieujawnione'
  const amount = salary.minimum === salary.maximum ? formatMoney(salary.minimum) : `${formatMoney(salary.minimum || 0)} – ${formatMoney(salary.maximum || 0)}`
  const unit = salary.unit === 'month' ? 'mies.' : salary.unit === 'hour' ? 'godz.' : salary.unit || ''
  return `${amount} ${salary.currency || ''} / ${unit}`
}

function sourceLabel(source) {
  return {
    rocketjobs: 'RocketJobs',
    justjoin: 'JustJoinIT',
    pracuj: 'Pracuj.pl',
  }[source] || source || 'Nieznane źródło'
}

function recommendationLabel(offer) {
  if (!offer.evaluation) return 'Nieoceniona'
  if (offer.evaluation_stale) return 'Ocena nieaktualna'
  return { aplikuj: 'Warto aplikować', 'sprawdź': 'Sprawdź ręcznie', 'pomiń': 'Pomiń' }[offer.evaluation.recommendation]
}

function recommendationClass(offer) {
  return offer.evaluation_stale ? 'stale' : offer.evaluation?.recommendation || 'none'
}

function offerCardLabel(offer) {
  return offer.decision === 'rejected' ? 'Odrzucona' : recommendationLabel(offer)
}

function offerCardClass(offer) {
  return offer.decision === 'rejected' ? 'rejected' : recommendationClass(offer)
}

function overviewLabel(offer) {
  if (submittedOfferIds.value.has(offer.id)) return 'Wysłano'
  if (pendingApprovedIds.value.has(offer.id)) return 'Zatwierdzona'
  if (offer.decision === 'rejected') return 'Odrzucona'
  return recommendationLabel(offer)
}

function overviewClass(offer) {
  if (submittedOfferIds.value.has(offer.id)) return 'submitted'
  if (pendingApprovedIds.value.has(offer.id)) return 'approved'
  if (offer.decision === 'rejected') return 'rejected'
  return recommendationClass(offer)
}

function offerForApplication(application) {
  return offers.value.find((offer) => offer.id === application.offer_id)
}

onMounted(() => {
  boot()
  clockTimer = setInterval(() => { clock.value = Date.now() }, 1000)
})
onUnmounted(() => {
  clearInterval(poller)
  clearInterval(clockTimer)
})
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">GetMeAJob</div>
      <nav class="side-nav">
        <button v-for="item in nav" :key="item.id" :class="['nav-item', { active: section === item.id }]" @click="pickSection(item.id)">
          <component :is="item.icon" :size="18" />
          <span>{{ item.label }}</span>
          <b v-if="item.id === 'offers' && counters.unrated">{{ counters.unrated }}</b>
          <b v-if="item.id === 'review' && counters.review">{{ counters.review }}</b>
          <b v-if="item.id === 'approved' && counters.approved">{{ counters.approved }}</b>
          <b v-if="item.id === 'rejected' && counters.rejected">{{ counters.rejected }}</b>
          <b v-if="item.id === 'submitted' && counters.submitted">{{ counters.submitted }}</b>
        </button>
      </nav>
    </aside>

    <main class="main">
      <header class="topbar"><div class="top-actions"><span v-if="operation.status === 'running'" class="operation-inline"><LoaderCircle :size="15" class="spin" /><span>{{ operation.message }}</span><small v-if="operationElapsed">{{ operationElapsed }}</small></span><button class="outline-button" @click="error = ''; showImport = true"><Link2 :size="16" /> Dodaj link</button><button class="primary-button" :disabled="operation.status === 'running'" @click="openSyncDialog"><RotateCw :size="16" :class="{ spin: operation.status === 'running' && operation.kind === 'sync' }" /> Pobierz oferty</button></div></header>

      <div v-if="notice" class="toast success"><Check :size="17" /> {{ notice }} <button @click="notice = ''"><X :size="15" /></button></div>
      <div v-if="error && !showSync && !showImport && !pendingBulkDecision && !pendingSubmission" class="toast error"><CircleAlert :size="17" /> {{ error }} <button @click="error = ''"><X :size="15" /></button></div>

      <template v-if="section === 'overview'">
        <div class="page-intro minimal-intro"><h1>Oferty</h1><div class="overview-heading-actions"><span class="count-line">{{ counters.all }} zapisanych</span><button v-if="counters.stale" class="outline-button" @click="startStaleEvaluation" :disabled="operation.status === 'running'"><RotateCw :size="16" /> Oceń ponownie nieaktualne <b>{{ counters.stale }}</b></button><button v-if="counters.unrated" class="outline-button" @click="startUnevaluatedEvaluation" :disabled="operation.status === 'running'"><Sparkles :size="16" /> Oceń nieocenione oferty <b>{{ counters.unrated }}</b></button></div></div>
        <div class="stats-grid">
          <div class="stat-card"><span>Nieocenione</span><strong>{{ counters.unrated }}</strong></div>
          <div class="stat-card"><span>Rekomendowane</span><strong>{{ counters.recommended }}</strong></div>
          <div class="stat-card"><span>Do sprawdzenia</span><strong>{{ counters.review }}</strong></div>
          <div class="stat-card"><span>Zatwierdzone</span><strong>{{ counters.approved }}</strong></div>
        </div>
        <details v-if="lastSyncReport" class="sync-report">
          <summary>Ostatnie pobieranie · {{ new Date(lastSyncReport.finished_at).toLocaleString('pl-PL') }} · {{ lastSyncReport.status === 'error' ? 'przerwane' : `${lastSyncReport.new} nowych, ${lastSyncReport.skipped} odrzuconych przez filtr` }}</summary>
          <p v-if="lastSyncReport.status === 'error'" class="sync-report-error">Przerwano: {{ lastSyncReport.error }}</p>
          <div v-for="source in lastSyncReport.sources" :key="source.id" class="sync-report-source">
            <strong>{{ source.label }}</strong>
            <span>{{ source.seen }} pobranych szczegółów · {{ source.matched }} pasujących · {{ source.new }} nowych · {{ source.skipped }} odrzuconych</span>
            <template v-if="source.discovery?.search_terms">
              <small>{{ source.discovery.pages_checked }} stron wyników · {{ source.discovery.listing_rows }} pozycji na listach · {{ source.discovery.title_filtered }} odrzuconych po tytule · {{ source.discovery.duplicates }} duplikatów · {{ source.discovery.candidates }} kandydatów · {{ source.discovery.details_failed ?? 0 }} błędów szczegółów</small>
              <small>Frazy: <span v-for="(count, term) in source.discovery.candidates_by_term" :key="term">{{ term }} ({{ count }}) · </span></small>
              <small v-if="source.discovery.search_limit_reached || source.discovery.term_limits_reached?.length || source.discovery.page_limits_reached?.length">Limity: <span v-if="source.discovery.search_limit_reached">łącznie {{ source.discovery.max_candidates }} kandydatów · </span><span v-if="source.discovery.term_limits_reached?.length">{{ source.discovery.max_candidates_per_term }} na frazę: {{ source.discovery.term_limits_reached.join(', ') }} · </span><span v-if="source.discovery.page_limits_reached?.length">{{ source.discovery.max_pages_per_term }} stron: {{ source.discovery.page_limits_reached.join(', ') }}</span></small>
              <small v-if="Object.keys(source.discovery.detail_errors || {}).length">Błędy szczegółów: <span v-for="(count, reason) in source.discovery.detail_errors" :key="reason">{{ reason }} ({{ count }}) · </span></small>
            </template>
            <ul v-if="Object.keys(source.skip_reasons || {}).length"><li v-for="(count, reason) in source.skip_reasons" :key="reason">{{ reason }}: {{ count }}</li></ul>
          </div>
        </details>
        <div class="section-heading"><h2>Ostatnie oferty</h2><button class="text-button" @click="pickSection('offers')">Nieocenione <ArrowRight :size="16" /></button></div>
        <div v-if="!offers.length" class="empty-card"><h3>Brak ofert</h3><button class="primary-button" :disabled="operation.status === 'running'" @click="openSyncDialog"><ArrowDownToLine :size="16" /> Pobierz oferty</button></div>
        <div v-else class="overview-list"><button v-for="offer in offers.slice(0, 5)" :key="offer.id" class="overview-row" @click="openOffer(offer)"><span class="company-avatar">{{ offer.company?.slice(0, 1) || '?' }}</span><span class="overview-info"><strong>{{ offer.title }}</strong><small>{{ offer.company }} · {{ offer.remote_mode === 'remote' ? 'Zdalnie' : offer.location }} · {{ sourceLabel(offer.source) }}</small></span><span :class="['recommendation', overviewClass(offer)]">{{ overviewLabel(offer) }}</span><ChevronRight :size="18" /></button></div>
      </template>

      <template v-else-if="['offers', 'review', 'approved', 'rejected'].includes(section)">
        <div class="page-intro compact minimal-intro"><h1>{{ activeTitle }}</h1><button v-if="section === 'offers' && counters.unrated" class="outline-button" @click="startUnevaluatedEvaluation" :disabled="operation.status === 'running'"><Sparkles :size="16" /> Oceń nieocenione oferty <b>{{ counters.unrated }}</b></button><button v-if="['review', 'approved', 'rejected'].includes(section) && counters.stale" class="outline-button" @click="startStaleEvaluation" :disabled="operation.status === 'running'"><RotateCw :size="16" /> Oceń ponownie nieaktualne <b>{{ counters.stale }}</b></button></div>
        <div v-if="section === 'review' && counters.review > counters.stale && decisionProfile" class="bulk-actions"><button class="primary-button" :disabled="!bulkEligible.approved" @click="bulkDecide('approved')"><Check :size="15" /> Zatwierdź ≥{{ decisionProfile.approve_min_score }}/100 <span v-if="bulkEligible.approved">({{ bulkEligible.approved }})</span></button><button class="soft-button danger" :disabled="!bulkEligible.rejected" @click="bulkDecide('rejected')"><ThumbsDown :size="15" /> Odrzuć &lt;{{ decisionProfile.reject_below_score }}/100 <span v-if="bulkEligible.rejected">({{ bulkEligible.rejected }})</span></button><span class="bulk-hint">Bez decyzji i z aktualną oceną · <button class="text-button" @click="pickSection('settings')">Zmień progi</button></span></div>
        <div class="list-toolbar"><div class="search-box"><Search :size="17" /><input v-model="search" placeholder="Szukaj stanowiska lub firmy…" /></div><span class="list-count">{{ visibleOffers.length }} {{ offerCountNoun(visibleOffers.length) }}</span></div>
        <div :class="['offers-layout', { 'empty-state': !visibleOffers.length }]">
          <div class="offer-list"><div v-if="!visibleOffers.length" class="list-empty">{{ emptyListMessage }}</div><button v-for="offer in visibleOffers" :key="offer.id" :class="['offer-card', { selected: selectedId === offer.id }]" @click="selectedId = offer.id"><div class="offer-card-head"><span class="company-avatar">{{ offer.company?.slice(0, 1) || '?' }}</span><span class="source-badge">{{ sourceLabel(offer.source) }}</span><span :class="['recommendation', offerCardClass(offer)]">{{ offerCardLabel(offer) }}</span><span v-if="offer.evaluation" class="offer-score">{{ offer.evaluation.score }}/100</span></div><strong>{{ offer.title }}</strong><span class="company-name">{{ offer.company }}</span><div class="offer-meta"><span><MapPin :size="14" /> {{ offer.remote_mode === 'remote' ? 'Zdalnie' : offer.remote_mode === 'hybrid' ? 'Hybrydowo' : offer.location || 'Nieznane' }}</span><span><Wallet :size="14" /> {{ salaryText(offer.salary) }}</span></div><div class="offer-card-bottom"><span>{{ offer.contract_types.join(' / ') || 'Umowa nieznana' }}</span><span v-if="submittedOfferIds.has(offer.id)" class="approved-text"><Check :size="13" /> Wysłano</span><span v-else-if="pendingApprovedIds.has(offer.id)" class="approved-text"><Check :size="13" /> Zatwierdzona</span><span v-else-if="offer.decision === 'rejected' && offer.evaluation_stale" class="stale-text">Ocena nieaktualna</span></div></button></div>
          <div v-if="selected" class="detail-panel"><div class="detail-top"><div class="detail-company"><span class="company-avatar large">{{ selected.company?.slice(0, 1) || '?' }}</span><div><span>OFERTA PRACY · {{ sourceLabel(selected.source) }}</span><h2>{{ selected.title }}</h2><p>{{ selected.company }} · {{ selected.location || 'Lokalizacja nieznana' }}</p></div></div><a :href="selected.url" target="_blank" rel="noopener noreferrer" class="icon-button" :title="`Otwórz oryginalną ofertę w ${sourceLabel(selected.source)}`"><ExternalLink :size="18" /></a></div><div class="detail-badges"><span class="source-detail-badge">Źródło: {{ sourceLabel(selected.source) }}</span><span><MapPin :size="14" /> {{ selected.remote_mode === 'remote' ? 'W pełni zdalnie' : selected.remote_mode }}</span><span><BriefcaseBusiness :size="14" /> {{ selected.contract_types.join(' / ') || 'Nieznana umowa' }}</span><span><Wallet :size="14" /> {{ salaryText(selected.salary) }}</span></div>
            <div class="detail-actions detail-actions-top"><button v-if="selected.evaluation && selectedApplication?.status !== 'submitted'" class="outline-button" :disabled="operation.status === 'running'" @click="startEvaluation([selected.id])"><RotateCw :size="15" /> Oceń ponownie</button><span class="actions-spacer"></span><span v-if="selectedApplication?.status === 'submitted'" class="submitted-label"><Check :size="15" /> Wysłano — decyzja jest zamknięta</span><template v-else-if="selected.decision === 'rejected'"><span class="rejected-label">Odrzucona</span><button class="outline-button" @click="decide('none')">Cofnij odrzucenie</button></template><template v-else><button class="soft-button danger" @click="decide('rejected')"><ThumbsDown :size="15" /> Odrzuć</button><button v-if="selected.decision === 'approved'" class="outline-button" @click="decide('none')">Cofnij zatwierdzenie</button><button v-if="selectedApplication?.status === 'approved'" class="primary-button" @click="markSubmitted(selectedApplication)"><BadgeCheck :size="16" /> Wysłane</button><button v-else class="primary-button" :disabled="!selected.evaluation || selected.evaluation_stale" @click="decide('approved')"><Check :size="16" /> Zatwierdź</button></template></div>
            <div v-if="selected.evaluation_stale" class="stale-notice"><CircleAlert :size="16" /><span>Ocena nieaktualna. Oferta lub profil zmieniły się od czasu analizy. Oceń ponownie przed zatwierdzeniem.</span></div>
            <div v-if="selected.evaluation" class="evaluation-block"><div class="evaluation-heading"><div><span class="eyebrow">OCENA DOPASOWANIA</span><h3 :class="recommendationClass(selected)">{{ recommendationLabel(selected) }}</h3></div><div class="score-ring">{{ selected.evaluation.score }}<small>/100</small></div></div><p class="rationale">{{ selected.evaluation.rationale }}</p><div v-if="selected.evaluation.requirements?.length" class="eval-section"><h4><Search :size="17" /> Faktyczne wymagania oferty</h4><ul><li v-for="requirement in selected.evaluation.requirements" :key="requirement">{{ requirement }}</li></ul></div><div v-if="selected.evaluation.matches?.length" class="eval-section"><h4><BadgeCheck :size="17" /> Dlaczego pasujesz</h4><div v-for="(match, index) in selected.evaluation.matches" :key="index" class="evidence"><strong>{{ match.requirement }}</strong><p>{{ match.explanation }}</p><small>Dowód z CV: {{ candidateProfile?.facts.find((fact) => fact.id === match.candidate_fact_id)?.text || match.candidate_fact_id }}</small></div></div><div v-if="selected.evaluation.gaps?.length" class="eval-section"><h4><CircleAlert :size="17" /> Luki i ryzyka</h4><ul><li v-for="gap in selected.evaluation.gaps" :key="gap">{{ gap }}</li></ul></div><div v-if="selected.evaluation.unknowns?.length" class="eval-section"><h4><Search :size="17" /> Co warto sprawdzić</h4><ul><li v-for="unknown in selected.evaluation.unknowns" :key="unknown">{{ unknown }}</li></ul></div></div>
            <div v-else class="unevaluated"><h3>Brak oceny</h3><button class="primary-button" :disabled="operation.status === 'running'" @click="startEvaluation([selected.id])"><Sparkles :size="16" /> Oceń ofertę</button></div>
            <details class="offer-description"><summary>Pełny opis oferty</summary><p>{{ selected.description }}</p></details>
          </div><div v-else-if="visibleOffers.length" class="detail-panel detail-empty">Wybierz ofertę z listy.</div>
        </div>
        <div v-if="section === 'approved' && counters.approved" class="codex-banner"><strong>Aplikowanie</strong><span>W Codex: „Zaaplikuj na zatwierdzone oferty z GetMeAJob”.</span></div>
      </template>

      <template v-else-if="section === 'submitted'"><div class="page-intro compact minimal-intro"><h1>Wysłane</h1></div><div v-if="!submittedApplications.length" class="empty-card"><h3>Brak wysłanych aplikacji</h3></div><div v-else class="history-table submitted-table"><div class="table-header"><span>STANOWISKO</span><span>DATA WYSŁANIA</span><span>NOTATKA</span></div><div v-for="application in submittedApplications" :key="application.id" class="table-row"><div><strong>{{ offerForApplication(application)?.title || application.offer_id }}</strong><small>{{ offerForApplication(application)?.company }}</small></div><span>{{ new Date(application.submitted_at).toLocaleDateString('pl-PL') }}</span><small>{{ application.confirmation || '—' }}</small></div></div></template>

      <template v-else-if="section === 'settings' && searchProfile">
        <div class="page-intro compact minimal-intro"><h1>Ustawienia</h1><button class="primary-button" :disabled="saving" @click="saveSettings"><Check :size="16" /> Zapisz</button></div>
        <div class="settings-grid">
          <section class="settings-card">
            <div class="settings-card-header"><h2>Filtry ofert</h2></div>
            <div class="field"><label>Role</label><input :value="searchProfile.roles.join(' · ')" disabled /></div>
            <div class="two-fields">
              <div class="field"><label>UoP brutto / mies. od</label><div class="input-suffix"><input v-model="searchProfile.minimum_uop_gross_pln_month" type="number" min="0" /><span>PLN</span></div></div>
              <div class="field"><label>B2B netto / mies. od</label><div class="input-suffix"><input v-model="searchProfile.minimum_b2b_net_pln_month" type="number" min="0" /><span>PLN</span></div></div>
            </div>
            <label class="toggle-row"><span><strong>Tylko zdalnie</strong></span><input v-model="searchProfile.remote_only" type="checkbox" /></label>
            <label class="toggle-row"><span><strong>Uwzględniaj oferty bez widełek</strong></span><input v-model="searchProfile.include_unknown_salary" type="checkbox" /></label>
            <div class="field"><label>Wykluczone frazy</label><input v-model="excludedText" placeholder="Oddziel przecinkami" /></div>
            <div v-if="decisionProfile" class="decision-thresholds"><h3>Decyzje zbiorcze</h3><div class="two-fields"><div class="field"><label>Zatwierdź od wyniku</label><div class="input-suffix"><input v-model="decisionProfile.approve_min_score" type="number" min="0" max="100" step="1" /><span>/100</span></div></div><div class="field"><label>Odrzuć poniżej wyniku</label><div class="input-suffix"><input v-model="decisionProfile.reject_below_score" type="number" min="0" max="100" step="1" /><span>/100</span></div></div></div><small>Zmiana progów nie zmienia wcześniejszych decyzji.</small></div>
          </section>
          <section class="settings-card">
            <div class="settings-card-header"><h2>CV i doświadczenie</h2></div>
            <div class="resume-upload"><strong>{{ resumeName || 'Brak CV' }}</strong><label class="outline-button">{{ resumeName ? 'Zmień PDF' : 'Wybierz PDF' }}<input type="file" accept="application/pdf,.pdf" hidden @change="uploadResume" /></label></div>
            <div class="field facts-field"><label>Fakty z CV</label><textarea v-model="candidateFactsText" rows="11"></textarea><small>Jeden fakt w wierszu. Po zmianie ocenę trzeba odświeżyć.</small></div>
          </section>
          <section class="settings-card danger-zone">
            <div><h2>Guzik zagłady</h2><p>Usuwa wszystkie oferty, oceny, decyzje, aplikacje i ustawienia. Najpierw zostanie utworzona pełna kopia bazy.</p></div>
            <button class="soft-button danger" :disabled="operation.status === 'running'" @click="error = ''; databaseResetConfirmation = ''; showDatabaseReset = true"><ThumbsDown :size="16" /> Wyczyść całą bazę</button>
          </section>
        </div>
      </template>
    </main>

    <div v-if="showSync" class="modal-backdrop" @click.self="!syncStarting && (showSync = false, error = '')"><div class="modal" role="dialog" aria-modal="true" aria-labelledby="sync-dialog-title"><h2 id="sync-dialog-title">Pobierz oferty</h2><p>Wybierz serwisy do przeszukania.</p><div class="sync-source-list"><label v-for="source in availableSources" :key="source.id" :class="['sync-source-option', { selected: selectedSyncSourceIds.includes(source.id) }]"><input v-model="selectedSyncSourceIds" type="checkbox" :value="source.id" :disabled="syncStarting" /><span>{{ source.label }}</span></label></div><p v-if="error" class="modal-error">{{ error }}</p><div class="modal-actions"><button class="outline-button" :disabled="syncStarting" @click="showSync = false; error = ''">Anuluj</button><button class="primary-button" :disabled="syncStarting || !selectedSyncSourceIds.length" @click="startSync">{{ syncStarting ? 'Uruchamiam…' : 'Pobierz z wybranych' }}</button></div></div></div>
    <div v-if="showImport" class="modal-backdrop" @click.self="showImport = false; error = ''"><div class="modal"><button class="modal-close" @click="showImport = false; error = ''"><X :size="18" /></button><h2>Dodaj ofertę</h2><p>Link z RocketJobs lub JustJoinIT</p><input v-model="importUrl" autofocus placeholder="https://justjoin.it/job-offer/…" @keyup.enter="importOffer" /><p v-if="error" class="modal-error">{{ error }}</p><div class="modal-actions"><button class="outline-button" @click="showImport = false; error = ''">Anuluj</button><button class="primary-button" :disabled="saving || !importUrl.trim()" @click="importOffer">{{ saving ? 'Pobieram…' : 'Dodaj' }}</button></div></div></div>
    <div v-if="pendingBulkDecision" class="modal-backdrop" @click.self="!bulkSaving && (pendingBulkDecision = null, error = '')"><div class="modal" role="dialog" aria-modal="true" aria-labelledby="bulk-dialog-title"><h2 id="bulk-dialog-title">{{ pendingBulkDecision.decision === 'approved' ? 'Zatwierdzić oferty?' : 'Odrzucić oferty?' }}</h2><p>{{ pendingBulkDecision.count }} {{ offerCountNoun(pendingBulkDecision.count) }} bez wcześniejszej decyzji, z aktualną oceną {{ pendingBulkDecision.decision === 'approved' ? `od ${pendingBulkDecision.threshold}` : `poniżej ${pendingBulkDecision.threshold}` }}/100. Akcja dotyczy wszystkich ofert, niezależnie od wyszukiwania.</p><p v-if="pendingBulkDecision.decision === 'approved'">CV nie zostanie wysłane automatycznie.</p><p v-if="error" class="modal-error">{{ error }}</p><div class="modal-actions"><button class="outline-button" :disabled="bulkSaving" @click="pendingBulkDecision = null; error = ''">Anuluj</button><button :class="pendingBulkDecision.decision === 'approved' ? 'primary-button' : 'soft-button danger'" :disabled="bulkSaving" @click="confirmBulkDecision">{{ bulkSaving ? 'Zapisuję…' : pendingBulkDecision.decision === 'approved' ? 'Zatwierdź oferty' : 'Odrzuć oferty' }}</button></div></div></div>
    <div v-if="pendingSubmission" class="modal-backdrop" @click.self="!submissionSaving && (pendingSubmission = null, error = '')"><div class="modal" role="dialog" aria-modal="true" aria-labelledby="submission-dialog-title"><h2 id="submission-dialog-title">Oznacz jako wysłane</h2><p>{{ offerForApplication(pendingSubmission)?.title || pendingSubmission.offer_id }}. Zapisz ten status dopiero po potwierdzeniu wysłania przez serwis rekrutacyjny.</p><div class="field"><label for="submission-confirmation">Notatka (opcjonalnie)</label><input id="submission-confirmation" v-model="submissionConfirmation" placeholder="Możesz zostawić puste" @keyup.enter="confirmSubmission" /></div><p v-if="error" class="modal-error">{{ error }}</p><div class="modal-actions"><button class="outline-button" :disabled="submissionSaving" @click="pendingSubmission = null; error = ''">Anuluj</button><button class="primary-button" :disabled="submissionSaving" @click="confirmSubmission">{{ submissionSaving ? 'Zapisuję…' : 'Oznacz wysłane' }}</button></div></div></div>
    <div v-if="showDatabaseReset" class="modal-backdrop" @click.self="!databaseResetSaving && (showDatabaseReset = false, error = '')"><div class="modal danger-modal" role="dialog" aria-modal="true" aria-labelledby="reset-dialog-title"><h2 id="reset-dialog-title">Wyczyścić całą bazę?</h2><p>Wszystkie oferty, oceny, decyzje, aplikacje i ustawienia zostaną usunięte. Przed resetem aplikacja zapisze kopię bezpieczeństwa.</p><div class="field"><label for="database-reset-confirmation">Aby potwierdzić, wpisz: <strong>USUŃ WSZYSTKO</strong></label><input id="database-reset-confirmation" v-model="databaseResetConfirmation" autofocus autocomplete="off" @keyup.enter="resetDatabase" /></div><p v-if="error" class="modal-error">{{ error }}</p><div class="modal-actions"><button class="outline-button" :disabled="databaseResetSaving" @click="showDatabaseReset = false; error = ''">Anuluj</button><button class="soft-button danger" :disabled="databaseResetSaving || databaseResetConfirmation !== 'USUŃ WSZYSTKO'" @click="resetDatabase">{{ databaseResetSaving ? 'Tworzę kopię i czyszczę…' : 'Tak, wyczyść wszystko' }}</button></div></div></div>
  </div>
</template>
