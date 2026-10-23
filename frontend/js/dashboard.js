/**
 * Dashboard Component Logic (ES Module)
 * Fetches analytics from /api/dashboard/stats and renders Chart.js visualizations.
 */

import { userId, fetchJson } from "./api.js";

let topicMasteryChartInstance = null;
let readinessDonutChartInstance = null;

// Initialize on DOM Ready
document.addEventListener("DOMContentLoaded", () => {
  displayScholarId();
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
    const stats = await fetchJson(`/api/dashboard/stats?user_id=${encodeURIComponent(userId)}`);
    renderMetrics(stats);
    renderTopicMasteryChart(stats.topics);
    renderReadinessDonut(stats.overall_readiness);
    renderTopicsList(stats.topics);
    setupWeakestTopicAction(stats.weakest_topic);
  } catch (error) {
    console.error("Failed to load dashboard data:", error);
    showErrorState();
  }
}

function renderMetrics(stats) {
  // 1. Overall Readiness
  const readinessEl = document.getElementById("val-readiness");
  const readinessBadge = document.getElementById("badge-readiness-status");
  if (readinessEl) readinessEl.textContent = `${stats.overall_readiness}%`;

  if (readinessBadge) {
    if (stats.total_questions_attempted === 0) {
      readinessBadge.textContent = "Needs Diagnostic";
      readinessBadge.className = "badge badge-warning";
    } else if (stats.overall_readiness >= 70) {
      readinessBadge.textContent = "Exam Ready";
      readinessBadge.className = "badge badge-success";
    } else if (stats.overall_readiness >= 40) {
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
  if (stats.weakest_topic) {
    if (weakestTitle) weakestTitle.textContent = stats.weakest_topic.name;
    if (weakestBtn) {
      weakestBtn.href = `/quiz?topic=${stats.weakest_topic.id}&n=5`;
      weakestBtn.textContent = `Practice ${stats.weakest_topic.name.split(" ")[0]} →`;
    }
  }
}

function renderTopicMasteryChart(topics) {
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

  const accuracyData = topics.map(t => t.accuracy);
  const targetData = topics.map(() => 80);

  topicMasteryChartInstance = new Chart(ctx, {
    type: "bar",
    data: {
      labels: labels,
      datasets: [
        {
          label: "Current Accuracy (%)",
          data: accuracyData,
          backgroundColor: "#0078d4",
          borderRadius: 6,
          barPercentage: 0.6,
          categoryPercentage: 0.7
        },
        {
          label: "Target Benchmark (80%)",
          data: targetData,
          backgroundColor: "rgba(148, 163, 184, 0.35)",
          borderColor: "#94a3b8",
          borderWidth: 1,
          borderDash: [4, 4],
          borderRadius: 6,
          barPercentage: 0.6,
          categoryPercentage: 0.7
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

function renderReadinessDonut(readinessScore) {
  const ctx = document.getElementById("readinessDonutChart")?.getContext("2d");
  const pctText = document.getElementById("donut-pct-text");
  const heading = document.getElementById("gauge-status-heading");
  const desc = document.getElementById("gauge-status-desc");

  if (pctText) pctText.textContent = `${readinessScore}%`;

  if (heading && desc) {
    if (readinessScore >= 80) {
      heading.textContent = "High Readiness";
      desc.textContent = "You are demonstrating strong mastery aligned with official Microsoft AZ-900 passing benchmarks.";
    } else if (readinessScore >= 60) {
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
    return `
      <div class="topic-item">
        <div class="topic-info">
          <div class="topic-title">
            <span>${escapeHtml(t.name)}</span>
            <span class="badge badge-azure">Weight: ${t.weight}x</span>
          </div>
          <div class="topic-meta">
            ${t.attempts} attempts • ${t.accuracy}% accuracy • ${t.coverage_pct}% coverage (${t.total_questions} questions available)
          </div>
          <div class="progress-track" title="Topic Readiness: ${t.readiness}%">
            <div class="progress-fill" style="width: ${Math.max(4, t.readiness)}%;"></div>
          </div>
        </div>
        <div class="topic-actions">
          <a href="/quiz?topic=${encodeURIComponent(t.id)}&n=5" class="btn btn-secondary btn-sm">
            Practice Domain
          </a>
        </div>
      </div>
    `;
  }).join("");
}

function setupWeakestTopicAction(weakestTopic) {
  const shortcutCard = document.getElementById("shortcut-weakest-card");
  const shortcutDesc = document.getElementById("shortcut-weakest-desc");

  if (!shortcutCard || !weakestTopic) return;

  if (shortcutDesc) {
    shortcutDesc.textContent = `Focus on ${weakestTopic.name} (Current: ${weakestTopic.accuracy}% accuracy).`;
  }

  shortcutCard.onclick = () => {
    window.location.href = `/quiz?topic=${encodeURIComponent(weakestTopic.id)}&n=5`;
  };
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
