/**
 * Azure Scholar AZ-900 | Flashcards Coach Application Logic
 * Integrates SM-2 spaced repetition, 3D flip card loop, and keyboard shortcuts.
 */

import { userId, fetchJson, postJson } from "./api.js";

// State
let topicsMap = {};
let currentDeck = [];
let currentIndex = 0;
let isFlipped = false;
let isSubmitting = false;
let selectedTopic = "all";

// Session Analytics
let sessionReviewedCount = 0;
let sessionCorrectCount = 0;

// DOM Elements
const scholarIdEl = document.getElementById("scholar-id-text");
const topicSelectEl = document.getElementById("fc-topic-select");
const errorBannerEl = document.getElementById("fc-error-banner");
const errorMessageEl = document.getElementById("fc-error-message");

const headlineEl = document.getElementById("fc-headline");
const sublineEl = document.getElementById("fc-subline");

// Views
const viewReviewEl = document.getElementById("view-review");
const viewSummaryEl = document.getElementById("view-summary");
const viewEmptyEl = document.getElementById("view-empty");

// Card Elements
const cardElement = document.getElementById("fc-card-element");
const frontTopicEl = document.getElementById("fc-front-topic");
const frontTypeEl = document.getElementById("fc-front-type");
const frontTextEl = document.getElementById("fc-front-text");

const backTopicEl = document.getElementById("fc-back-topic");
const backTypeEl = document.getElementById("fc-back-type");
const backTextEl = document.getElementById("fc-back-text");
const hintContainerEl = document.getElementById("fc-hint-container");
const hintTextEl = document.getElementById("fc-hint-text");

const progressTextEl = document.getElementById("fc-progress-text");
const statusBadgeEl = document.getElementById("fc-status-badge");
const progressFillEl = document.getElementById("fc-progress-fill");

const controlsUnflippedEl = document.getElementById("fc-controls-unflipped");
const controlsFlippedEl = document.getElementById("fc-controls-flipped");
const btnShowAnswer = document.getElementById("btn-show-answer");

// Summary Elements
const summaryCardsDoneEl = document.getElementById("summary-cards-done");
const summaryAccuracyEl = document.getElementById("summary-accuracy");
const summaryTomorrowDueEl = document.getElementById("summary-tomorrow-due");
const summaryStreakEl = document.getElementById("summary-streak");
const btnReviewAgain = document.getElementById("btn-review-again");


/**
 * Show friendly error notification
 */
function showError(message) {
  if (errorBannerEl && errorMessageEl) {
    errorMessageEl.textContent = message || "An unexpected error occurred. Please try again.";
    errorBannerEl.style.display = "flex";
  }
}

function clearError() {
  if (errorBannerEl) {
    errorBannerEl.style.display = "none";
  }
}


/**
 * Format cloze deletions with styled blank underscores
 */
function formatClozeText(text) {
  if (!text) return "";
  return text.replace(/\[\.\.\.\]/g, `<span class="fc-cloze-blank">[...]</span>`);
}


/**
 * Load topics list for filter dropdown
 */
async function loadTopics() {
  try {
    const topics = await fetchJson("/api/topics");
    topicsMap = {};
    if (topicSelectEl) {
      topicSelectEl.innerHTML = `<option value="all">All Syllabus Topics</option>`;
      topics.forEach((t) => {
        topicsMap[t.id] = t.name;
        const opt = document.createElement("option");
        opt.value = t.id;
        opt.textContent = `${t.name} (${t.question_count || 0})`;
        topicSelectEl.appendChild(opt);
      });
    }
  } catch (err) {
    console.error("Failed to load topics:", err);
  }
}


/**
 * Fetch due & new cards from backend
 */
async function loadDeck() {
  clearError();
  try {
    headlineEl.textContent = "Loading flashcards...";
    const topicParam = selectedTopic !== "all" ? `&topic=${encodeURIComponent(selectedTopic)}` : "";
    const data = await fetchJson(`/api/cards/due?user_id=${encodeURIComponent(userId)}${topicParam}&new_limit=15`);

    currentDeck = data.cards || [];
    currentIndex = 0;
    sessionReviewedCount = 0;
    sessionCorrectCount = 0;

    const totalCount = currentDeck.length;
    const minutes = data.estimated_minutes || (totalCount > 0 ? Math.max(1, Math.ceil(totalCount * 25 / 60)) : 0);

    if (totalCount === 0) {
      headlineEl.textContent = "0 cards due today";
      sublineEl.textContent = "All caught up with scheduled reviews!";
      showView("empty");
      return;
    }

    headlineEl.textContent = `${totalCount} card${totalCount === 1 ? "" : "s"} due, about ${minutes} minute${minutes === 1 ? "" : "s"}`;
    sublineEl.textContent = `Daily Session · ${data.due_count} overdue/due, ${data.new_count} new`;

    showView("review");
    renderCurrentCard();
  } catch (err) {
    console.error("Failed to load cards:", err);
    showError("Could not connect to the flashcards server. Please ensure the backend is running.");
    headlineEl.textContent = "Unable to load deck";
  }
}


/**
 * Switch view visibility
 */
function showView(viewName) {
  if (viewReviewEl) viewReviewEl.style.display = viewName === "review" ? "block" : "none";
  if (viewSummaryEl) viewSummaryEl.style.display = viewName === "summary" ? "block" : "none";
  if (viewEmptyEl) viewEmptyEl.style.display = viewName === "empty" ? "block" : "none";
}


/**
 * Render current card state
 */
function renderCurrentCard() {
  if (currentIndex >= currentDeck.length) {
    showSummary();
    return;
  }

  const card = currentDeck[currentIndex];
  isFlipped = false;

  // Unflip 3D card
  if (cardElement) {
    cardElement.classList.remove("is-flipped");
  }

  // Update controls
  if (controlsUnflippedEl) controlsUnflippedEl.style.display = "block";
  if (controlsFlippedEl) controlsFlippedEl.style.display = "none";

  // Topic display name
  const topicName = topicsMap[card.topic_id] || card.topic_id || "Azure Fundamentals";
  const typeLabel = card.type === "cloze" ? "Cloze Deletion" : "Basic Concept";

  // Front Face
  if (frontTopicEl) frontTopicEl.textContent = topicName;
  if (frontTypeEl) frontTypeEl.textContent = typeLabel;
  if (frontTextEl) {
    if (card.type === "cloze") {
      frontTextEl.innerHTML = formatClozeText(card.front);
    } else {
      frontTextEl.textContent = card.front;
    }
  }

  // Back Face
  if (backTopicEl) backTopicEl.textContent = topicName;
  if (backTypeEl) backTypeEl.textContent = "Key Concept";
  if (backTextEl) backTextEl.textContent = card.back;

  // Hint
  if (card.hint && card.hint.trim()) {
    if (hintTextEl) hintTextEl.textContent = `Hint: ${card.hint.trim()}`;
    if (hintContainerEl) hintContainerEl.style.display = "flex";
  } else {
    if (hintContainerEl) hintContainerEl.style.display = "none";
  }

  // Progress Bar
  const total = currentDeck.length;
  if (progressTextEl) progressTextEl.textContent = `Card ${currentIndex + 1} of ${total}`;
  if (progressFillEl) {
    const pct = Math.round(((currentIndex) / total) * 100);
    progressFillEl.style.width = `${pct}%`;
  }

  // Status Badge
  if (statusBadgeEl) {
    if (card.is_new) {
      statusBadgeEl.textContent = "New Card";
      statusBadgeEl.className = "fc-badge-new";
    } else {
      statusBadgeEl.textContent = "Review Due";
      statusBadgeEl.className = "fc-badge-due";
    }
  }

  // Update dynamic interval preview buttons (e.g. "Again · 1d", "Good · 3d")
  const intervals = card.intervals || { "0": 1, "1": 1, "2": 3, "3": 4 };
  setButtonInterval("interval-label-0", "Again", intervals["0"]);
  setButtonInterval("interval-label-1", "Hard", intervals["1"]);
  setButtonInterval("interval-label-2", "Good", intervals["2"]);
  setButtonInterval("interval-label-3", "Easy", intervals["3"]);
}


/**
 * Helper to label rating button interval
 */
function setButtonInterval(elId, name, intervalDays) {
  const el = document.getElementById(elId);
  if (el) {
    el.textContent = `${intervalDays}d`;
  }
}


/**
 * Flip card to reveal answer
 */
function flipCard() {
  if (isFlipped) return;
  isFlipped = true;
  if (cardElement) cardElement.classList.add("is-flipped");
  if (controlsUnflippedEl) controlsUnflippedEl.style.display = "none";
  if (controlsFlippedEl) controlsFlippedEl.style.display = "block";
}


/**
 * Submit rating for current card
 */
async function rateCard(rating) {
  if (isSubmitting || currentIndex >= currentDeck.length) return;
  isSubmitting = true;
  clearError();

  const card = currentDeck[currentIndex];
  try {
    await postJson("/api/cards/review", {
      user_id: userId,
      card_id: card.id,
      rating: rating
    });

    sessionReviewedCount++;
    if (rating > 0) {
      sessionCorrectCount++;
    }

    currentIndex++;
    renderCurrentCard();
  } catch (err) {
    console.error("Failed to submit rating:", err);
    showError("Could not record review. Please check your internet connection.");
  } finally {
    isSubmitting = false;
  }
}


/**
 * Display session summary screen
 */
async function showSummary() {
  showView("summary");
  headlineEl.textContent = "Session Complete";
  sublineEl.textContent = "All scheduled cards reviewed successfully!";

  const acc = sessionReviewedCount > 0 ? Math.round((sessionCorrectCount / sessionReviewedCount) * 100) : 100;
  if (summaryCardsDoneEl) summaryCardsDoneEl.textContent = sessionReviewedCount;
  if (summaryAccuracyEl) summaryAccuracyEl.textContent = `${acc}%`;

  try {
    const stats = await fetchJson(`/api/cards/stats?user_id=${encodeURIComponent(userId)}`);
    if (summaryStreakEl) summaryStreakEl.textContent = `${stats.streak || 1} 🔥`;
    if (summaryTomorrowDueEl) summaryTomorrowDueEl.textContent = stats.due_today || 0;
  } catch (err) {
    console.warn("Could not fetch final stats:", err);
    if (summaryStreakEl) summaryStreakEl.textContent = "1 🔥";
    if (summaryTomorrowDueEl) summaryTomorrowDueEl.textContent = "0";
  }
}


/**
 * Keyboard shortcuts setup
 * Space: flip
 * 1-4: rating (Again, Hard, Good, Easy) when flipped
 */
function handleKeyDown(e) {
  // Ignore if typing inside an input/select
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT" || e.target.tagName === "TEXTAREA") {
    return;
  }

  // Space to flip
  if (e.code === "Space" || e.key === " ") {
    if (viewReviewEl && viewReviewEl.style.display !== "none") {
      e.preventDefault();
      if (!isFlipped) {
        flipCard();
      }
    }
  }

  // 1-4 to rate
  if (isFlipped && !isSubmitting && viewReviewEl && viewReviewEl.style.display !== "none") {
    if (e.key === "1") {
      e.preventDefault();
      rateCard(0); // Again
    } else if (e.key === "2") {
      e.preventDefault();
      rateCard(1); // Hard
    } else if (e.key === "3") {
      e.preventDefault();
      rateCard(2); // Good
    } else if (e.key === "4") {
      e.preventDefault();
      rateCard(3); // Easy
    }
  }
}


/**
 * Event Listeners & Initialization
 */
function initEvents() {
  if (btnShowAnswer) {
    btnShowAnswer.addEventListener("click", flipCard);
  }

  if (cardElement) {
    cardElement.addEventListener("click", () => {
      if (!isFlipped) flipCard();
    });
  }

  // Rating buttons
  for (let r = 0; r <= 3; r++) {
    const btn = document.getElementById(`btn-rate-${r}`);
    if (btn) {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        rateCard(r);
      });
    }
  }

  // Topic filter
  if (topicSelectEl) {
    topicSelectEl.addEventListener("change", (e) => {
      selectedTopic = e.target.value;
      loadDeck();
    });
  }

  // Review again
  if (btnReviewAgain) {
    btnReviewAgain.addEventListener("click", () => {
      loadDeck();
    });
  }

  // Keyboard navigation
  window.addEventListener("keydown", handleKeyDown);
}


// Bootstrap
document.addEventListener("DOMContentLoaded", async () => {
  if (scholarIdEl) {
    scholarIdEl.textContent = userId;
  }

  initEvents();
  await loadTopics();
  await loadDeck();
});
