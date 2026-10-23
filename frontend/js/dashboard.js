/**
 * Dashboard Component Logic (ES Module)
 * Fetches analytics from /api/dashboard/stats and renders Chart.js visualizations.
 */

import { userId, fetchJson, postJson } from "./api.js";

let topicMasteryChartInstance = null;
let readinessDonutChartInstance = null;
let readinessTrendChartInstance = null;

// Initialize on DOM Ready
document.addEventListener("DOMContentLoaded", () => {
  displayScholarId();
  document.getElementById("exam-setup-form")?.addEventListener("submit", saveExamPlan);
  loadDashboardData();
});

function displayScholarId() {
  const scholarTag = document.getElementById("scholar-id-text");
  if (scholarTag) {
    scholarTag.textContent = userId;
  }
}

async function loadDashboardData() {
  try {
    const userQuery = `user_id=${encodeURIComponent(userId)}`;
    const [stats, readiness] = await Promise.all([
      fetchJson(`/api/dashboard/stats?${userQuery}`),
      fetchJson(`/api/readiness?${userQuery}`)
    ]);
    const plan = await fetchJson(`/api/plan/today?${userQuery}`);
    const trend = await fetchJson(`/api/readiness/trend?${userQuery}`);
    renderMetrics(stats, readiness);
    renderTrackerSummary(readiness);
    renderExamSetup(readiness);
    renderPlan(plan);
    renderReadinessTrend(trend);
    renderTopicMasteryChart(readiness.topics, readiness.target_score);
    renderReadinessDonut(readiness.overall ?? 0, readiness.target_score);
    renderTopicsList(readiness.topics);
    setupWeakestTopicAction(getWeakestTopic(readiness.topics) || stats.weakest_topic);
  } catch (error) {
    console.error("Failed to load dashboard data:", error);
    showErrorState();
  }
}

function renderMetrics(stats, readiness) {
  // 1. Overall Readiness
  const readinessEl = document.getElementById("val-readiness");
  const readinessBadge = document.getElementById("badge-readiness-status");
  const score = readiness.overall ?? 0;
  const targetScore = readiness.target_score;
  if (readinessEl) readinessEl.textContent = `${score}%`;

  if (readinessBadge) {
    if (!readiness.has_activity) {
      readinessBadge.textContent = "Needs Diagnostic";
      readinessBadge.className = "badge badge-warning";
    } else if (score >= targetScore) {
      readinessBadge.textContent = "Exam Ready";
      readinessBadge.className = "badge badge-success";
    } else if (score >= targetScore * 0.7) {
      readinessBadge.textContent = "In Progress";
      readinessBadge.className = "badge badge-azure";
    } else {
      readinessBadge.textContent = "Developing";
      readinessBadge.className = "badge badge-danger";
    }
  }

  // 2. Questions Solved
  const attemptsEl = document.getElementById("val-attempts");
  const correctCountEl = document.getElementById("val-correct-count");
  if (attemptsEl) attemptsEl.textContent = stats.total_questions_attempted;
  if (correctCountEl) {
    correctCountEl.textContent = `${stats.total_correct} correct of ${stats.total_questions_attempted} attempts`;
  }

  // 3. Accuracy Rate
  const accuracyEl = document.getElementById("val-accuracy");
  const accuracyBadge = document.getElementById("val-accuracy-badge");
  if (accuracyEl) accuracyEl.textContent = `${stats.overall_accuracy}%`;
  if (accuracyBadge) {
    if (stats.overall_accuracy >= 80) {
      accuracyBadge.textContent = "High Precision";
      accuracyBadge.className = "badge badge-success";
    } else if (stats.overall_accuracy >= 60) {
      accuracyBadge.textContent = "Passing Zone";
      accuracyBadge.className = "badge badge-azure";
    } else if (stats.total_questions_attempted > 0) {
      accuracyBadge.textContent = "Review Needed";
      accuracyBadge.className = "badge badge-warning";
    } else {
      accuracyBadge.textContent = "Not Started";
      accuracyBadge.className = "badge badge-azure";
    }
  }

  // 4. Focus / Weakest Topic
  const weakestTitle = document.getElementById("val-weakest-title");
  const weakestBtn = document.getElementById("btn-practice-weakest");
  const weakestTopic = getWeakestTopic(readiness.topics) || stats.weakest_topic;
  if (weakestTopic) {
    if (weakestTitle) weakestTitle.textContent = weakestTopic.name;
    if (weakestBtn) {
      weakestBtn.href = `/quiz?topic=${encodeURIComponent(weakestTopic.id)}&n=5`;
      weakestBtn.textContent = `Practice ${weakestTopic.name.split(" ")[0]} →`;
    }
  }
}

function renderTopicMasteryChart(topics, targetScore) {
  const ctx = document.getElementById("topicMasteryChart")?.getContext("2d");
  if (!ctx || !window.Chart) return;

  if (topicMasteryChartInstance) {
    topicMasteryChartInstance.destroy();
  }

  const labels = topics.map(t => {
    // Shorten topic names for clear chart labels
    if (t.name.includes("concepts")) return "Cloud Concepts";
    if (t.name.includes("architecture")) return "Azure Architecture";
    if (t.name.includes("management")) return "Azure Governance";
    return t.name;
  });

  const readinessData = topics.map(t => t.readiness);
  const colors = topics.map(t => {
    if (t.readiness === null) return "#94a3b8";
    if (t.readiness < 50) return "#d13438";
    if (t.readiness <= 75) return "#b45309";
    return "#107c41";
  });

  topicMasteryChartInstance = new Chart(ctx, {
    type: "bar",
    data: {
      labels: labels,
      datasets: [
        {
          label: "Topic readiness (%)",
          data: readinessData,
          backgroundColor: colors,
          borderRadius: 6,
          barPercentage: 0.6,
          categoryPercentage: 0.7
        },
        {
          label: `Target (${targetScore}%)`,
          data: topics.map(() => targetScore),
          type: "line",
          pointRadius: 0,
          borderColor: "#475569",
          borderDash: [5, 5],
          borderWidth: 1.5
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "top",
          labels: {
            boxWidth: 12,
            font: { family: "'Segoe UI', sans-serif", size: 12 }
          }
        },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${ctx.raw}%`
          }
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          max: 100,
          ticks: {
            stepSize: 20,
            callback: (v) => `${v}%`,
            font: { family: "'Segoe UI', sans-serif" }
          },
          grid: {
            color: "rgba(226, 232, 240, 0.8)"
          }
        },
        x: {
          ticks: {
            font: { family: "'Segoe UI', sans-serif", weight: "600" }
          },
          grid: {
            display: false
          }
        }
      }
    }
  });
}

function renderReadinessDonut(readinessScore, targetScore) {
  const ctx = document.getElementById("readinessDonutChart")?.getContext("2d");
  const pctText = document.getElementById("donut-pct-text");
  const heading = document.getElementById("gauge-status-heading");
  const desc = document.getElementById("gauge-status-desc");

  if (pctText) pctText.textContent = `${readinessScore}%`;

  if (heading && desc) {
    if (readinessScore >= targetScore) {
      heading.textContent = "High Readiness";
      desc.textContent = `You have reached your ${targetScore}% readiness target.`;
    } else if (readinessScore >= targetScore * 0.7) {
      heading.textContent = "Intermediate Progress";
      desc.textContent = "Good foundation. Target your weaker domains to reliably clear the 700/1000 passing threshold.";
    } else if (readinessScore > 0) {
      heading.textContent = "Early Learning Phase";
      desc.textContent = "Continue taking topical quizzes to expand question bank coverage and improve accuracy.";
    } else {
      heading.textContent = "Diagnostic Required";
      desc.textContent = "Complete your first diagnostic test to benchmark your Azure skills against the syllabus.";
    }
  }

  if (!ctx || !window.Chart) return;

  if (readinessDonutChartInstance) {
    readinessDonutChartInstance.destroy();
  }

  const remaining = Math.max(0, 100 - readinessScore);

  readinessDonutChartInstance = new Chart(ctx, {
    type: "doughnut",
    data: {
      datasets: [
        {
          data: [readinessScore, remaining],
          backgroundColor: ["#0078d4", "#e2e8f0"],
          borderWidth: 0,
          circumference: 360,
          rotation: -90
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "78%",
      plugins: {
        legend: { display: false },
        tooltip: { enabled: false }
      }
    }
  });
}

function renderTopicsList(topics) {
  const container = document.getElementById("topics-container");
  if (!container) return;

  if (!topics || topics.length === 0) {
    container.innerHTML = `<div style="padding: 1.5rem; text-align: center; color: var(--text-muted);">No syllabus topics registered.</div>`;
    return;
  }

  container.innerHTML = topics.map(t => {
    const score = t.readiness;
    const barColor = score === null ? "#94a3b8"
      : score < 50 ? "#d13438"
      : score <= 75 ? "#b45309"
      : "#107c41";
    const scoreLabel = score === null ? "Unknown" : `${score}%`;
    const signal = [
      `Quiz ${t.quiz_accuracy === null ? "—" : `${t.quiz_accuracy}%`}`,
      `Cards ${t.card_mastery === null ? "—" : `${t.card_mastery}%`}`,
      `Recent activity ${t.recency}%`,
      `${t.attempts} quiz answers`
    ].join(" • ");
    return `
      <div class="topic-item">
        <div class="topic-info">
          <div class="topic-title">
            <span>${escapeHtml(t.name)}</span>
            <span class="badge badge-azure">${scoreLabel} readiness</span>
          </div>
          <div class="topic-meta">
            ${signal}
          </div>
          <div class="progress-track" title="Topic readiness: ${scoreLabel}">
            <div class="progress-fill" style="width: ${score === null ? 0 : score}%; background: ${barColor};"></div>
          </div>
        </div>
        <div class="topic-actions">
          <a href="/quiz?topic=${encodeURIComponent(t.id)}&n=5" class="btn btn-secondary btn-sm">
            Quiz
          </a>
          <a href="/flashcards?topic=${encodeURIComponent(t.id)}" class="btn btn-secondary btn-sm">
            Cards
          </a>
        </div>
      </div>
    `;
  }).join("");
}

function renderTrackerSummary(readiness) {
  const countdown = document.getElementById("exam-countdown");
  const delta = document.getElementById("readiness-delta");
  const modeBadge = document.getElementById("readiness-mode");
  if (countdown) {
    if (readiness.days_left === null) {
      countdown.textContent = "Set an exam date to start your countdown";
    } else if (readiness.days_left === 0) {
      countdown.textContent = readiness.exam_passed ? "Exam date has passed" : "Exam day";
    } else {
      countdown.textContent = `${readiness.days_left} days until your exam`;
    }
  }
  if (delta) {
    const change = Number(readiness.delta_7d || 0);
    delta.textContent = `Weekly readiness change: ${change > 0 ? "+" : ""}${change.toFixed(1)}%`;
  }
  if (modeBadge) {
    const mode = readiness.mode || "intensive";
    modeBadge.textContent = `${mode[0].toUpperCase()}${mode.slice(1)} mode`;
    modeBadge.className = `badge ${mode === "polish" ? "badge-success" : mode === "steady" ? "badge-azure" : "badge-warning"}`;
  }
  const targetLabel = document.getElementById("readiness-target-label");
  const chartTitle = document.getElementById("topic-chart-title");
  if (targetLabel) targetLabel.textContent = `Target: ${readiness.target_score}%+`;
  if (chartTitle) chartTitle.textContent = `Topic Readiness vs Target (${readiness.target_score}%)`;
}

function renderExamSetup(readiness) {
  const examDate = document.getElementById("exam-date");
  const dailyMinutes = document.getElementById("daily-minutes");
  const targetScore = document.getElementById("target-score");
  const course = document.getElementById("exam-course");
  const status = document.getElementById("exam-setup-status");
  if (examDate) examDate.value = readiness.exam_date || "";
  if (dailyMinutes) dailyMinutes.value = readiness.daily_minutes || 45;
  if (targetScore) targetScore.value = readiness.target_score ?? 85;
  if (course) course.value = readiness.course || "AZ-900";
  if (status) {
    status.textContent = readiness.exam_date ? "Exam configured" : "No exam configured";
    status.className = `badge ${readiness.exam_date ? "badge-success" : "badge-azure"}`;
  }
}

async function saveExamPlan(event) {
  event.preventDefault();
  const message = document.getElementById("exam-form-message");
  const payload = {
    user_id: userId,
    exam_date: document.getElementById("exam-date").value,
    daily_minutes: Number(document.getElementById("daily-minutes").value),
    target_score: Number(document.getElementById("target-score").value),
    course: document.getElementById("exam-course").value.trim() || "AZ-900"
  };
  if (message) {
    message.textContent = "";
    message.className = "form-message";
  }
  try {
    await postJson("/api/exams", payload);
    if (message) {
      message.textContent = "Exam plan saved.";
      message.className = "form-message form-message-success";
    }
    await loadDashboardData();
  } catch (error) {
    if (message) {
      message.textContent = `Unable to save exam plan: ${error.message}`;
      message.className = "form-message form-message-error";
    }
  }
}

function renderPlan(plan) {
  const container = document.getElementById("today-plan");
  const total = document.getElementById("plan-minutes");
  const note = document.getElementById("plan-coach-note");
  if (!container) return;
  if (total) total.textContent = `${plan.minutes_total} minutes`;
  if (note) note.textContent = plan.coach_note || "";
  if (!plan.items.length) {
    container.innerHTML = `<p class="empty-state">No study tasks are needed today. Keep your learning streak going.</p>`;
    return;
  }
  const activityLabels = {
    diagnostic: "Take a diagnostic quiz",
    flashcards: "Review due flashcards",
    quiz: "Practice topic",
    mock: "Take a mock exam",
    review: "Light review (exam taper)"
  };
  container.innerHTML = plan.items.map(item => {
    const label = activityLabels[item.activity] || item.activity;
    const href = item.activity === "diagnostic"
      ? "/quiz?mode=diagnostic&n=15"
      : item.activity === "flashcards" || item.activity === "review"
        ? item.topic_id ? `/flashcards?topic=${encodeURIComponent(item.topic_id)}` : "/flashcards"
        : item.activity === "mock"
          ? "/quiz?mode=mock&n=20"
          : `/quiz?topic=${encodeURIComponent(item.topic_id || "all")}&n=5`;
    return `
      <div class="plan-item${item.done ? " plan-item-done" : ""}">
        <label class="plan-check">
          <input type="checkbox" data-plan-id="${item.id}" ${item.done ? "checked disabled" : ""} aria-label="Mark ${escapeHtml(label)} complete">
          <span>${escapeHtml(label)}</span>
        </label>
        <a href="${href}" class="plan-link">${item.minutes} min${item.count ? ` · ${item.count} cards` : ""}</a>
      </div>
    `;
  }).join("");
  container.querySelectorAll("[data-plan-id]").forEach(checkbox => {
    checkbox.addEventListener("change", async event => {
      const input = event.currentTarget;
      const row = input.closest(".plan-item");
      input.disabled = true;
      try {
        await postJson(`/api/plan/${input.dataset.planId}/done`, { user_id: userId });
        row.classList.add("plan-item-done");
      } catch (error) {
        input.checked = false;
        console.error("Failed to mark study task complete:", error);
        if (note) note.textContent = `Could not save task completion: ${error.message}`;
      } finally {
        input.disabled = false;
      }
    });
  });
}

function renderReadinessTrend(trend) {
  const canvas = document.getElementById("readinessTrendChart");
  const wrapper = canvas?.parentElement;
  if (!canvas || !window.Chart) return;
  const snapshots = trend.snapshots || [];
  const projection = trend.projection;
  if (readinessTrendChartInstance) readinessTrendChartInstance.destroy();
  if (!snapshots.length) {
    canvas.hidden = true;
    let empty = wrapper.querySelector(".empty-state");
    if (!empty) {
      empty = document.createElement("p");
      empty.className = "empty-state";
      wrapper.appendChild(empty);
    }
    empty.textContent = "Your readiness trend will appear after you complete a quiz or review flashcards.";
    return;
  }
  canvas.hidden = false;
  wrapper.querySelector(".empty-state")?.remove();
  const labels = snapshots.map(item => item.date);
  const history = snapshots.map(item => item.readiness);
  const projected = snapshots.map(() => null);
  if (projection) {
    labels.push(projection.date);
    history.push(null);
    projected[projected.length - 1] = snapshots[snapshots.length - 1].readiness;
    projected.push(projection.readiness);
  }
  readinessTrendChartInstance = new Chart(canvas.getContext("2d"), {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Readiness",
          data: history,
          borderColor: "#0078d4",
          backgroundColor: "rgba(0, 120, 212, 0.12)",
          fill: true,
          tension: 0.25,
          pointRadius: 3
        },
        ...(projection ? [{
          label: "Exam-day projection",
          data: projected,
          borderColor: "#64748b",
          borderDash: [6, 5],
          tension: 0,
          pointRadius: 3,
          fill: false
        }] : [])
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: {
          min: 0,
          max: 100,
          ticks: { callback: value => `${value}%` }
        }
      }
    }
  });
}

function setupWeakestTopicAction(weakestTopic) {
  const shortcutCard = document.getElementById("shortcut-weakest-card");
  const shortcutDesc = document.getElementById("shortcut-weakest-desc");

  if (!shortcutCard || !weakestTopic) return;

  if (shortcutDesc) {
    const readiness = weakestTopic.readiness;
    const detail = readiness === null || readiness === undefined
      ? `${weakestTopic.accuracy ?? 0}% quiz accuracy`
      : `${readiness}% readiness`;
    shortcutDesc.textContent = `Focus on ${weakestTopic.name} (Current: ${detail}).`;
  }

  shortcutCard.onclick = () => {
    window.location.href = `/quiz?topic=${encodeURIComponent(weakestTopic.id)}&n=5`;
  };
}

function getWeakestTopic(topics) {
  return (topics || [])
    .filter(topic => topic.readiness !== null)
    .sort((left, right) => left.readiness - right.readiness)[0];
}

function showErrorState() {
  const container = document.getElementById("topics-container");
  if (container) {
    container.innerHTML = `
      <div style="padding: 2rem; text-align: center; color: var(--color-danger);">
        ⚠️ Unable to load dashboard analytics from the server. Verify that the FastAPI backend is running.
      </div>
    `;
  }
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
