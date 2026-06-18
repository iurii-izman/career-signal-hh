/* CareerSignal HH — Local Web UI JavaScript */
(function () {
  "use strict";
  var activeJobId = null,
    jobPollTimer = null,
    dashboardData = null;
  var $ = function (s) {
    return document.querySelector(s);
  };
  var $$ = function (s) {
    return document.querySelectorAll(s);
  };
  function now() {
    return new Date().toLocaleTimeString("ru-RU", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }
  function fmtDate(iso) {
    if (!iso) return "-";
    return iso.replace("T", " ").substring(0, 19);
  }
  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }
  function showToast(msg, ok) {
    var c = $("#toast-container");
    var t = document.createElement("div");
    t.className = "toast " + (ok ? "ok" : "error");
    t.innerHTML =
      "<span>" +
      escapeHtml(msg) +
      '</span><button class="toast-close" onclick="this.parentElement.remove()">&times;</button>';
    c.appendChild(t);
    setTimeout(function () {
      if (t.parentElement) t.remove();
    }, 5000);
  }
  var logCleared = false;
  function addLog(msg, cls) {
    if (!logCleared) {
      var d = $("#log-default");
      if (d) d.remove();
      logCleared = true;
    }
    var panel = $("#log-panel"),
      entry = document.createElement("div");
    entry.className = "log-entry " + (cls || "muted");
    entry.innerHTML =
      '<span class="log-time">[' + now() + "]</span> " + escapeHtml(msg);
    panel.appendChild(entry);
    panel.scrollTop = panel.scrollHeight;
  }
  async function apiGet(url) {
    return (await fetch(url)).json();
  }
  async function apiPost(url, body) {
    return (
      await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      })
    ).json();
  }
  // ── Dashboard ────────────────────────────────────────────────────────
  async function loadDashboard() {
    try {
      var r = await apiGet("/api/dashboard");
      if (r && r.ok && r.data) {
        dashboardData = r.data;
        renderDashboard(r.data);
        $("#db-status").textContent =
          "DB: " + (r.data.total_vacancies || 0) + " vacancies";
        $("#db-status").className = "status-indicator ok";
      }
    } catch (e) {
      addLog("Dashboard error: " + e.message, "error");
    }
  }
  function renderDashboard(data) {
    setStat("stat-total", data.total_vacancies, "");
    setStat("stat-new", data.new_24h, "accent");
    setStat("stat-pending", data.pending_queue, "");
    setStat("stat-strong", data.strong_matches, "success");
    setStat("stat-applied", data.applied, "");
    setStat("stat-interview", data.interview, "");
    setStat("stat-offer", data.offer, "");
    setStat("stat-avgscore", data.avg_score, "muted");
    // Extended status
    var ext = document.getElementById("ext-status");
    if (ext) {
      ext.innerHTML = [
        [
          "Search",
          data.latest_search_run ? fmtDate(data.latest_search_run) : "none",
        ],
        [
          "Backup",
          (data.backup_overdue ? "\u26a0 " : "") +
            (data.latest_backup || "none"),
        ],
        ["Export", data.latest_export || "none"],
        ["Clusters", data.cluster_count || 0],
        ["Calibration", data.calibration_count || 0],
      ]
        .map(function (r) {
          return (
            '<div class="card info-card"><div class="card-label">' +
            r[0] +
            '</div><div class="card-value muted">' +
            r[1] +
            "</div></div>"
          );
        })
        .join("");
    }
    // Action plan
    var plan = document.getElementById("action-plan");
    if (plan) {
      plan.innerHTML = getActionPlan(data)
        .map(function (a) {
          var icon =
            a.priority === "high"
              ? "\uD83D\uDD34"
              : a.priority === "medium"
                ? "\uD83D\uDFE1"
                : "\uD83D\uDFE2";
          return (
            '<div class="plan-card plan-priority-' +
            a.priority +
            '"><span class="plan-icon">' +
            icon +
            '</span><span class="plan-label">' +
            escapeHtml(a.label) +
            '</span><button class="btn btn-sm" data-action="' +
            a.action +
            '">Go</button></div>'
          );
        })
        .join("");
    }
    // Follow-ups
    var fu = document.getElementById("follow-ups-panel");
    if (fu && data.follow_ups && data.follow_ups.length) {
      fu.innerHTML = data.follow_ups
        .map(function (f) {
          return (
            '<div class="fu-item"><span class="fu-name">' +
            escapeHtml(f.name || "") +
            " @ " +
            escapeHtml(f.employer_name || "") +
            '</span><span class="fu-date">Applied: ' +
            (f.applied_at || "").substring(0, 10) +
            '</span><a class="btn btn-sm" href="/vacancy/' +
            f.id +
            '">View</a><button class="btn btn-sm fu-followup" data-fuid="' +
            f.id +
            '">Follow-up tmrw</button></div>'
          );
        })
        .join("");
    }
    // Reports
    var rp = document.getElementById("reports-panel");
    if (rp && data.reports && data.reports.length) {
      rp.innerHTML = data.reports
        .map(function (r) {
          return (
            '<a class="report-link" href="/' +
            r.path +
            '" target="_blank">\uD83D\uDCC4 ' +
            escapeHtml(r.label) +
            "</a>"
          );
        })
        .join(" ");
    }
  }
  function getActionPlan(data) {
    var p = [];
    if (data.pending_queue > 0)
      p.push({
        action: "review-queue-link",
        label: "Review " + data.pending_queue + " pending vacancies",
        priority: "high",
      });
    if (!data.latest_search_run)
      p.push({
        action: "run-autopilot",
        label: "Run first autopilot daily scan",
        priority: "high",
      });
    else {
      try {
        var h = Math.round(
          (Date.now() - new Date(data.latest_search_run).getTime()) / 3600000,
        );
        if (h > 24)
          p.push({
            action: "run-autopilot",
            label: "Search stale (" + h + "h ago)",
            priority: "medium",
          });
      } catch (e) {}
    }
    if (data.backup_overdue)
      p.push({
        action: "run-backup",
        label: "Backup overdue",
        priority: "high",
      });
    if (!data.latest_backup)
      p.push({
        action: "run-backup",
        label: "Create first backup",
        priority: "medium",
      });
    if (data.follow_ups && data.follow_ups.length)
      p.push({
        action: "follow-up-scroll",
        label: "Follow up " + data.follow_ups.length + " applied",
        priority: "medium",
      });
    if (data.calibration_count > 0)
      p.push({
        action: "calibrate-job",
        label: "Review " + data.calibration_count + " calibration suggestions",
        priority: "low",
      });
    if (data.cluster_count > 0)
      p.push({
        action: "quality-cluster-job",
        label: "Review " + data.cluster_count + " duplicate clusters",
        priority: "low",
      });
    p.push({
      action: "run-health",
      label: "Run health check",
      priority: "low",
    });
    return p;
  }
  function setStat(id, value, cls) {
    var el = $("#" + id);
    if (el) {
      el.textContent = value != null ? value : "-";
      el.className = "card-value" + (cls ? " " + cls : "");
    }
  }
  // ── Health ───────────────────────────────────────────────────────────
  async function loadHealth() {
    try {
      var r = await apiGet("/api/health");
      if (r && r.ok && r.data) {
        var failed = r.data.filter(function (c) {
          return c.status === "FAIL";
        }).length;
        var warned = r.data.filter(function (c) {
          return c.status === "WARN";
        }).length;
        var h = $("#health-status");
        if (failed > 0) {
          h.textContent = "Health: " + failed + " FAIL";
          h.className = "status-indicator fail";
        } else if (warned > 0) {
          h.textContent = "Health: " + warned + " WARN";
          h.className = "status-indicator warn";
        } else {
          h.textContent = "Health: OK";
          h.className = "status-indicator ok";
        }
      }
    } catch (e) {
      $("#health-status").textContent = "Health: error";
      $("#health-status").className = "status-indicator fail";
    }
  }
  // ── Jobs ─────────────────────────────────────────────────────────────
  function showJobCard(job) {
    var card = $("#job-card");
    if (!card) return;
    card.style.display = "block";
    $("#job-name").textContent = job.name || "-";
    $("#job-progress-fill").style.width = (job.progress || 0) + "%";
    $("#job-progress-pct").textContent = (job.progress || 0) + "%";
    $("#job-message").textContent = job.message || "";
    $("#job-status").textContent = job.status || "queued";
    $("#job-status").className =
      "job-card-status job-status-" + (job.status || "queued");
    $("#job-cancel-btn").style.display =
      job.status === "running" || job.status === "queued"
        ? "inline-block"
        : "none";
    if (
      job.status === "success" ||
      job.status === "failed" ||
      job.status === "cancelled"
    )
      stopJobPolling();
  }
  function startJobPolling(jobId) {
    activeJobId = jobId;
    if (jobPollTimer) clearInterval(jobPollTimer);
    jobPollTimer = setInterval(pollJob, 2000);
    pollJob();
  }
  function stopJobPolling() {
    if (jobPollTimer) {
      clearInterval(jobPollTimer);
      jobPollTimer = null;
    }
    setTimeout(function () {
      if (activeJobId) loadRecentJobs();
    }, 5000);
    activeJobId = null;
  }
  async function pollJob() {
    if (!activeJobId) return;
    try {
      var r = await apiGet("/api/jobs/" + activeJobId);
      if (r && r.ok && r.data) showJobCard(r.data);
    } catch (e) {
      addLog("Poll error: " + e.message, "error");
    }
  }
  async function cancelActiveJob() {
    if (!activeJobId) return;
    var r = await apiPost("/api/jobs/" + activeJobId + "/cancel");
    showToast(r && r.ok ? "Cancelled" : r.message || "Failed", r && r.ok);
  }
  async function loadRecentJobs() {
    try {
      var r = await apiGet("/api/jobs?limit=10");
      if (r && r.ok && r.data) renderRecentJobs(r.data);
    } catch (e) {}
  }
  function renderRecentJobs(jobs) {
    var c = $("#recent-jobs");
    if (!c) return;
    if (!jobs || !jobs.length) {
      c.innerHTML = '<div class="log-entry muted">No jobs yet</div>';
      return;
    }
    c.innerHTML = jobs
      .map(function (j) {
        var icon =
          j.status === "success"
            ? "\u2713"
            : j.status === "failed"
              ? "\u2717"
              : j.status === "running"
                ? "\u25B6"
                : "\u25CB";
        var t = j.started_at
          ? fmtDate(j.started_at)
          : j.finished_at
            ? fmtDate(j.finished_at)
            : "-";
        return (
          '<div class="job-row job-row-status-' +
          (j.status || "queued") +
          '"><span class="job-row-icon">' +
          icon +
          '</span><span class="job-row-name">' +
          escapeHtml(j.name) +
          '</span><span class="job-row-status">' +
          (j.status || "-") +
          '</span><span class="job-row-progress">' +
          (j.progress || 0) +
          '%</span><span class="job-row-time">' +
          t +
          "</span></div>" +
          (j.error
            ? '<div class="job-row-error">' + escapeHtml(j.error) + "</div>"
            : "")
        );
      })
      .join("");
  }
  async function runJobAction(label, endpoint, body) {
    addLog("Starting: " + label, "info");
    try {
      var r = await apiPost(endpoint, body);
      if (r && r.ok && r.data) {
        showJobCard(r.data);
        startJobPolling(r.data.id);
        showToast("Job started: " + label, true);
        loadRecentJobs();
      } else {
        showToast((r && r.message) || "Failed", false);
        addLog("Rejected: " + ((r && r.message) || "unknown"), "error");
      }
    } catch (e) {
      showToast("Error: " + e.message, false);
      addLog("Error: " + e.message, "error");
    }
  }
  // ── Main event delegation ────────────────────────────────────────────
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-action]");
    if (!btn) return;
    var action = btn.getAttribute("data-action");
    switch (action) {
      case "run-health":
        addLog("Running health check...", "info");
        apiPost("/api/actions/health").then(function (r) {
          if (r && r.ok) {
            addLog("Health OK", "success");
            showToast("Health OK", true);
            loadDashboard();
            loadHealth();
          } else {
            addLog("Health: " + ((r && r.message) || "failed"), "error");
            showToast((r && r.message) || "Failed", false);
          }
        });
        break;
      case "run-autopilot":
        runJobAction("autopilot-daily", "/api/jobs/autopilot-daily", {
          mode: "normal",
        });
        break;
      case "search-smoke":
        runJobAction("search-smoke", "/api/jobs/search-smoke", {});
        break;
      case "export-all":
        runJobAction("export-all", "/api/jobs/export-all", {});
        break;
      case "quality-cluster-job":
        runJobAction("quality-cluster", "/api/jobs/quality-cluster", {});
        break;
      case "calibrate-job":
        runJobAction("calibrate-suggest", "/api/jobs/calibrate-suggest", {});
        break;
      case "job-cancel":
        cancelActiveJob();
        break;
      case "review-queue-link":
        window.location.href = "/queue";
        break;
      case "run-backup":
        addLog("Creating backup...", "info");
        apiPost("/api/jobs/export-all", {}).then(function () {
          showToast("Export started (includes backup)");
          loadDashboard();
        });
        break;
      case "follow-up-scroll":
        var el = document.getElementById("follow-ups-panel");
        if (el) el.scrollIntoView({ behavior: "smooth" });
        break;
    }
    // Queue card actions from queue page
    var qbtn = e.target.closest("[data-va]");
    if (qbtn) {
      var vid = qbtn.getAttribute("data-vid");
      var va = qbtn.getAttribute("data-va");
      if (!vid) return;
      if (
        va === "interesting" ||
        va === "maybe" ||
        va === "rejected" ||
        va === "archived"
      ) {
        apiPost("/api/vacancies/" + vid + "/status", { status: va }).then(
          function (r) {
            showToast(r.message, r.ok);
          },
        );
      } else if (va === "apply-pack") {
        apiPost("/api/vacancies/" + vid + "/apply-pack").then(function (r) {
          showToast(r.message, r.ok);
          addLog(
            "Apply pack: " + (r.message || ""),
            r.ok ? "success" : "error",
          );
        });
      } else if (va === "applied") {
        apiPost("/api/vacancies/" + vid + "/applied", { date: "today" }).then(
          function (r) {
            showToast(r.message, r.ok);
          },
        );
      }
    }
    // Follow-up buttons
    var fbtn = e.target.closest(".fu-followup");
    if (fbtn) {
      var fuid = fbtn.getAttribute("data-fuid");
      if (fuid) {
        apiPost("/api/follow-ups/" + fuid + "/next-action").then(function (r) {
          showToast(r.message, r.ok);
          loadDashboard();
        });
      }
    }
  });
  // ── Clock ────────────────────────────────────────────────────────────
  function updateClock() {
    var el = $("#status-clock");
    if (el)
      el.textContent = new Date().toLocaleString("ru-RU", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
  }
  // ── Init ─────────────────────────────────────────────────────────────
  function init() {
    updateClock();
    setInterval(updateClock, 1000);
    loadDashboard();
    loadHealth();
    loadRecentJobs();
    setInterval(loadDashboard, 30000);
    setInterval(loadHealth, 30000);
    setInterval(loadRecentJobs, 15000);
  }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
