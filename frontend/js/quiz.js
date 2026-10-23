/**
 * Smart Quiz Builder Engine (ES Module)
 * Manages Quiz Lifecycle: Topic Selection -> Active Question -> Immediate Feedback -> Score Summary.
 * Supports weighted question sampling, persistent user attempts, and retrying missed questions.
 */

import { userId, fetchJson, postJson } from "./api.js";

// State Management
let currentQuizQuestions = [];
let currentQuestionIndex = 0;
let selectedOptionIndex = null;
let currentMode = "topic";
let selectedTopicId = "all";
let correctAnswersCount = 0;
let missedQuestions = [];
let perTopicScores = {}; // topic_id -> { name: string, total: number, correct: number }

// Stopwatch Timer
let timerInterval = null;
let timerSeconds = 0;

// DOM View References
const viewSetup = document.getElementById("view-setup");
const viewQuiz = document.getElementById("view-quiz");
const viewSummary = document.getElementById("view-summary");

document.addEventListener("DOMContentLoaded", async () => {
  displayScholarId();
  await initSetupView();
  checkUrlParamsForAutoStart();
});

function displayScholarId() {
  const scholarTag = document.getElementById("scholar-id-text");
  if (scholarTag) {
    scholarTag.textContent = userId;
  }
}

/**
 * Initialize Setup View: fetch available topics and render selector cards
 */
async function initSetupView() {
  try {
    const topics = await fetchJson("/api/topics");
    const container = document.getElementById("setup-topic-options");
    if (!container) return;

    // Retain the 'all' mixed mock card and append domain topics
    const topicCardsHtml = topics.map(t => `
      <div class="topic-select-card" data-topic-id="${escapeHtml(t.id)}">
        <div class="topic-select-title">${escapeHtml(t.name)}</div>
        <div class="topic-select-desc">Weight: ${t.weight}x • ${t.question_count} practice questions available</div>
      </div>
    `).join("");

    container.innerHTML = `
      <div class="topic-select-card selected" data-topic-id="all">
        <div class="topic-select-title">⚡ Mixed Mock Exam</div>
        <div class="topic-select-desc">Stratified sample across all official AZ-900 domains with 3x wrong-answer weighting.</div>
      </div>
      ${topicCardsHtml}
    `;

    // Add click listeners to cards
    const cards = container.querySelectorAll(".topic-select-card");
    cards.forEach(card => {
      card.addEventListener("click", () => {
        cards.forEach(c => c.classList.remove("selected"));
        card.classList.add("selected");
        selectedTopicId = card.getAttribute("data-topic-id");
      });
    });

    // Start button handler
    const startBtn = document.getElementById("btn-start-quiz");
    if (startBtn) {
      startBtn.addEventListener("click", () => {
        const countSelect = document.getElementById("select-question-count");
        const count = countSelect ? parseInt(countSelect.value, 10) : 5;
        const mode = selectedTopicId === "all" ? "mock" : "topic";
        startQuizSession(selectedTopicId, count, mode);
      });
    }
  } catch (error) {
    console.error("Failed to load topics:", error);
  }
}

/**
 * Check if page was loaded with direct query parameters (e.g. from Dashboard shortcuts)
 */
function checkUrlParamsForAutoStart() {
  const params = new URLSearchParams(window.location.search);
  const topicParam = params.get("topic");
  const modeParam = params.get("mode");
  const countParam = params.get("n");

  if (topicParam || modeParam) {
    const targetTopic = topicParam || "all";
    const count = countParam ? parseInt(countParam, 10) : 5;
    const mode = modeParam || (targetTopic === "all" ? "mock" : "topic");

    selectedTopicId = targetTopic;
    startQuizSession(targetTopic, count, mode);
  }
}

/**
 * Start a new quiz session by requesting questions from the backend
 */
async function startQuizSession(topicId, count, mode) {
  try {
    currentMode = mode;
    const url = `/api/quiz?topic=${encodeURIComponent(topicId)}&n=${count}&user_id=${encodeURIComponent(userId)}&mode=${encodeURIComponent(mode)}`;
    
    // Show loading state
    if (viewSetup) viewSetup.style.display = "none";
    if (viewSummary) viewSummary.style.display = "none";
    if (viewQuiz) viewQuiz.style.display = "block";

    const questionPromptEl = document.getElementById("question-text");
    if (questionPromptEl) questionPromptEl.textContent = "Sampling questions from knowledge base...";

    const questions = await fetchJson(url);

    if (!questions || questions.length === 0) {
      alert("No questions found for the selected topic criteria.");
      resetToSetupView();
      return;
    }

    // Reset quiz state
    currentQuizQuestions = questions;
    currentQuestionIndex = 0;
    correctAnswersCount = 0;
    missedQuestions = [];
    perTopicScores = {};

    // Initialize per-topic score counters
    questions.forEach(q => {
      if (!perTopicScores[q.topic_id]) {
        perTopicScores[q.topic_id] = {
          name: q.topic_name,
          total: 0,
          correct: 0
        };
      }
      perTopicScores[q.topic_id].total += 1;
    });

    startTimer();
    renderCurrentQuestion();
  } catch (error) {
    console.error("Failed to start quiz session:", error);
    alert("Unable to load quiz questions. Please check the backend connection.");
    resetToSetupView();
  }
}

/**
 * Render the active question view
 */
function renderCurrentQuestion() {
  selectedOptionIndex = null;
  const q = currentQuizQuestions[currentQuestionIndex];
  if (!q) {
    showSummaryView();
    return;
  }

  // Update Progress and Meta
  const progressText = document.getElementById("quiz-progress-text");
  const progressFill = document.getElementById("quiz-progress-fill");
  const topicBadge = document.getElementById("quiz-topic-badge");
  const questionPrompt = document.getElementById("question-text");
  const optionsContainer = document.getElementById("options-container");
  const feedbackContainer = document.getElementById("feedback-container");
  const submitBtn = document.getElementById("btn-submit-answer");
  const nextBtn = document.getElementById("btn-next-question");

  if (progressText) {
    progressText.textContent = `Question ${currentQuestionIndex + 1} of ${currentQuizQuestions.length}`;
  }
  if (progressFill) {
    const pct = ((currentQuestionIndex) / currentQuizQuestions.length) * 100;
    progressFill.style.width = `${pct}%`;
  }
  if (topicBadge) {
    topicBadge.textContent = q.topic_name || "AZ-900 Domain";
  }
  if (questionPrompt) {
    questionPrompt.textContent = q.question;
  }

  // Hide feedback, reset buttons
  if (feedbackContainer) feedbackContainer.style.display = "none";
  if (submitBtn) {
    submitBtn.style.display = "inline-flex";
    submitBtn.disabled = true;
    submitBtn.textContent = "Check Answer";
  }
  if (nextBtn) nextBtn.style.display = "none";

  // Build Option Buttons (Labeled A, B, C, D)
  const optionLetters = ["A", "B", "C", "D"];
  if (optionsContainer) {
    optionsContainer.innerHTML = q.options.map((optText, index) => `
      <button class="option-btn" data-index="${index}" id="option-${index}">
        <span class="option-letter">${optionLetters[index]}</span>
        <span class="option-label">${escapeHtml(optText)}</span>
      </button>
    `).join("");

    // Bind selection events
    const optionBtns = optionsContainer.querySelectorAll(".option-btn");
    optionBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        if (btn.disabled) return;
        optionBtns.forEach(b => b.classList.remove("selected"));
        btn.classList.add("selected");
        selectedOptionIndex = parseInt(btn.getAttribute("data-index"), 10);
        if (submitBtn) submitBtn.disabled = false;
      });
    });
  }

  // Bind submit button
  if (submitBtn) {
    submitBtn.onclick = () => submitCurrentAnswer();
  }
}

/**
 * Submit the chosen answer to the server for verification and attempt recording
 */
async function submitCurrentAnswer() {
  if (selectedOptionIndex === null) return;

  const q = currentQuizQuestions[currentQuestionIndex];
  const submitBtn = document.getElementById("btn-submit-answer");
  const nextBtn = document.getElementById("btn-next-question");
  const feedbackContainer = document.getElementById("feedback-container");
  const feedbackIcon = document.getElementById("feedback-icon");
  const feedbackTitle = document.getElementById("feedback-title");
  const feedbackExplanation = document.getElementById("feedback-explanation");
  const optionBtns = document.querySelectorAll(".option-btn");

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = "Verifying...";
  }

  try {
    const payload = {
      user_id: userId,
      question_id: q.id,
      chosen_index: selectedOptionIndex,
      mode: currentMode
    };

    const result = await postJson("/api/quiz/attempt", payload);

    // Disable all options so they cannot be changed
    optionBtns.forEach(b => {
      b.disabled = true;
    });

    const isCorrect = result.correct;
    const correctIndex = result.correct_index;

    // Apply visual styling to option buttons
    optionBtns.forEach((btn, idx) => {
      if (idx === correctIndex) {
        btn.classList.add("correct");
      }
      if (idx === selectedOptionIndex && !isCorrect) {
        btn.classList.add("incorrect");
      }
    });

    // Update Scores
    if (isCorrect) {
      correctAnswersCount += 1;
      if (perTopicScores[q.topic_id]) {
        perTopicScores[q.topic_id].correct += 1;
      }
    } else {
      missedQuestions.push(q);
    }

    // Reveal Feedback Callout
    if (feedbackContainer) {
      feedbackContainer.style.display = "flex";
      feedbackContainer.className = `feedback-box ${isCorrect ? "is-correct" : "is-incorrect"}`;
    }
    if (feedbackIcon) feedbackIcon.textContent = isCorrect ? "✓" : "✗";
    if (feedbackTitle) feedbackTitle.textContent = isCorrect ? "Correct Answer! Great Job." : "Incorrect.";
    if (feedbackExplanation) feedbackExplanation.textContent = result.explanation;

    // Toggle Action Buttons
    if (submitBtn) submitBtn.style.display = "none";
    if (nextBtn) {
      nextBtn.style.display = "inline-flex";
      const isLast = (currentQuestionIndex === currentQuizQuestions.length - 1);
      nextBtn.textContent = isLast ? "Finish & View Results →" : "Next Question →";
      nextBtn.onclick = () => {
        currentQuestionIndex += 1;
        renderCurrentQuestion();
      };
    }

    // Update progress bar to include this answered question
    const progressFill = document.getElementById("quiz-progress-fill");
    if (progressFill) {
      const pct = ((currentQuestionIndex + 1) / currentQuizQuestions.length) * 100;
      progressFill.style.width = `${pct}%`;
    }

  } catch (error) {
    console.error("Failed to verify attempt:", error);
    alert("Error recording answer on server.");
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = "Check Answer";
    }
  }
}

/**
 * Show the final Score Summary View
 */
function showSummaryView() {
  stopTimer();

  if (viewQuiz) viewQuiz.style.display = "none";
  if (viewSummary) viewSummary.style.display = "block";

  const total = currentQuizQuestions.length;
  const scorePct = total > 0 ? Math.round((correctAnswersCount / total) * 100) : 0;
  const passed = scorePct >= 70; // 70% passing standard for AZ-900

  const scoreDisplay = document.getElementById("summary-score-display");
  const subtitle = document.getElementById("summary-subtitle");
  const passBadge = document.getElementById("summary-pass-badge");
  const iconLarge = document.getElementById("summary-badge-icon");
  const breakdownRows = document.getElementById("summary-breakdown-rows");
  const retryBtn = document.getElementById("btn-retry-missed");
  const missedCountTag = document.getElementById("missed-count-tag");
  const restartBtn = document.getElementById("btn-restart-quiz");

  if (scoreDisplay) scoreDisplay.textContent = `${scorePct}%`;
  if (subtitle) {
    subtitle.textContent = `You correctly answered ${correctAnswersCount} of ${total} questions in ${formatTime(timerSeconds)}.`;
  }

  if (passBadge && iconLarge) {
    if (passed) {
      passBadge.textContent = "Exam Passing Benchmark Achieved (>=70%)";
      passBadge.className = "badge badge-success";
      iconLarge.textContent = "🏆";
      iconLarge.className = "summary-icon-large summary-icon-pass";
    } else {
      passBadge.textContent = "Needs Review (<70% Benchmark)";
      passBadge.className = "badge badge-danger";
      iconLarge.textContent = "📈";
      iconLarge.className = "summary-icon-large summary-icon-fail";
    }
  }

  // Populate Domain Breakdown Rows
  if (breakdownRows) {
    breakdownRows.innerHTML = Object.entries(perTopicScores).map(([_, data]) => {
      const topicPct = data.total > 0 ? Math.round((data.correct / data.total) * 100) : 0;
      const badgeClass = topicPct >= 70 ? "badge-success" : "badge-warning";
      return `
        <tr>
          <td><strong>${escapeHtml(data.name)}</strong></td>
          <td>${data.correct} / ${data.total}</td>
          <td><span class="badge ${badgeClass}">${topicPct}%</span></td>
        </tr>
      `;
    }).join("");
  }

  // Retry Missed Questions Trigger
  if (retryBtn) {
    if (missedQuestions.length > 0) {
      retryBtn.style.display = "inline-flex";
      if (missedCountTag) missedCountTag.textContent = missedQuestions.length;
      retryBtn.onclick = () => {
        // Relaunch using only missed questions
        currentQuizQuestions = [...missedQuestions];
        currentQuestionIndex = 0;
        correctAnswersCount = 0;
        missedQuestions = [];
        startTimer();
        if (viewSummary) viewSummary.style.display = "none";
        if (viewQuiz) viewQuiz.style.display = "block";
        renderCurrentQuestion();
      };
    } else {
      retryBtn.style.display = "none";
    }
  }

  // Restart Quiz button
  if (restartBtn) {
    restartBtn.onclick = () => resetToSetupView();
  }
}

/**
 * Reset views back to initial topic setup
 */
function resetToSetupView() {
  stopTimer();
  if (viewQuiz) viewQuiz.style.display = "none";
  if (viewSummary) viewSummary.style.display = "none";
  if (viewSetup) viewSetup.style.display = "block";
}

/**
 * Stopwatch Utilities
 */
function startTimer() {
  stopTimer();
  timerSeconds = 0;
  updateTimerDisplay();
  timerInterval = setInterval(() => {
    timerSeconds += 1;
    updateTimerDisplay();
  }, 1000);
}

function stopTimer() {
  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
}

function updateTimerDisplay() {
  const display = document.getElementById("timer-display");
  if (display) {
    display.textContent = formatTime(timerSeconds);
  }
}

function formatTime(totalSecs) {
  const mins = Math.floor(totalSecs / 60).toString().padStart(2, "0");
  const secs = (totalSecs % 60).toString().padStart(2, "0");
  return `${mins}:${secs}`;
}

function escapeHtml(str) {
  if (!str) return "";
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
