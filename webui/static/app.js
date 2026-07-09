// 2秒ごとに /api/state を取得して描き直す素朴な構成。
const $ = (id) => document.getElementById(id);

// arm（比較条件）の日本語説明。UIの分かりやすさの中心。
const ARM_INFO = {
  mock: {
    title: "配管テスト",
    desc: "AIを使わず、模範解答を書き込むだけ。計測の仕組み自体が動くかの確認用。",
    needs: [],
    cost: "無料・すぐ終わる",
  },
  local_only: {
    title: "ローカルLLMだけ",
    desc: "Mac上のモデル（LM Studio）に全部やらせる。ローカルの実力を見る。",
    needs: ["lm"],
    cost: "無料（電気代のみ）",
  },
  cloud_only: {
    title: "Claudeだけ【基準】",
    desc: "全部Claudeに任せる。これが比較の基準線（ベースライン）。",
    needs: ["claude"],
    cost: "サブスク枠を消費",
  },
  router: {
    title: "ルーター【本命】",
    desc: "簡単そうならローカル、難しそうならClaudeへ自動で振り分ける。",
    needs: ["lm", "claude"],
    cost: "ローカルで済んだ分だけ節約",
  },
};

let S = null;          // 最新の state
let built = false;     // カード類を生成済みか
const selectedArms = new Set(["mock"]);
let selectedTask = ""; // "" = すべて

function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;"); }

// ---- 環境バッジ ----
function renderEnv() {
  const h = S.health;
  $("env").innerHTML = `
    <span class="badge ${h.lm_studio ? "on" : "off"}"
          title="${h.lm_studio ? "モデル: " + (h.lm_model || "不明") : "LM Studioを起動し、DeveloperタブでServerをStartしてください"}">
      ${h.lm_studio ? "✓" : "✗"} LM Studio</span>
    <span class="badge ${h.claude_cli ? "on" : "off"}"
          title="${h.claude_cli ? "claude コマンドが見つかりました" : "claude CLI が見つかりません"}">
      ${h.claude_cli ? "✓" : "✗"} Claude CLI</span>`;
}

// ---- ステップ1: タスクカード ----
function buildTasks() {
  const all = [{ id: "", category: "", prompt: "登録されている全タスクを順番に実行します。", target_file: "", budget: null }]
    .concat(S.tasks);
  $("task-cards").innerHTML = all.map((t) => {
    const isAll = t.id === "";
    return `<label class="card sel" data-task="${t.id}">
      <input type="radio" name="task" value="${t.id}" ${t.id === selectedTask ? "checked" : ""}>
      <div class="body">
        <div class="title">${isAll ? "すべてのタスク" : t.id}
          ${isAll ? "" : `<span class="tag">${t.category}</span>`}</div>
        ${isAll
          ? `<div class="desc">${esc(t.prompt)}</div>`
          : `<div class="desc">${esc(t.prompt.length > 80 ? t.prompt.slice(0, 80) + "…" : t.prompt)}</div>
             <details class="more" onclick="event.stopPropagation()">
               <summary>指示の全文と上限を見る</summary>
               <pre>${esc(t.prompt)}</pre>
               <div class="limits">上限: $${t.budget.max_cost_usd} ／ ${t.budget.max_turns}ターン ／ ${t.budget.max_wall_s}秒
                 — 超えたら「失敗」扱い（暴走対策）</div>
             </details>`}
      </div></label>`;
  }).join("");
  document.querySelectorAll('input[name="task"]').forEach((r) => {
    r.onchange = () => { selectedTask = r.value; renderPlan(); };
  });
}

// ---- ステップ2: armカード ----
function buildArms() {
  $("arm-cards").innerHTML = S.arms.map((a) => {
    const info = ARM_INFO[a] || { title: a, desc: "", needs: [], cost: "" };
    return `<label class="card sel" data-arm="${a}">
      <input type="checkbox" value="${a}" ${selectedArms.has(a) ? "checked" : ""}>
      <div class="body">
        <div class="title">${info.title} <span class="tag mono">${a}</span></div>
        <div class="desc">${info.desc}</div>
        <div class="reqs" data-needs="${info.needs.join(",")}"></div>
        <div class="cost">${info.cost}</div>
      </div></label>`;
  }).join("");
  document.querySelectorAll('#arm-cards input').forEach((c) => {
    c.onchange = () => {
      c.checked ? selectedArms.add(c.value) : selectedArms.delete(c.value);
      renderPlan();
    };
  });
}

// 環境チェック結果を armカードの必要条件表示に反映
function renderArmReqs() {
  const h = S.health;
  document.querySelectorAll("#arm-cards .reqs").forEach((el) => {
    const needs = el.dataset.needs ? el.dataset.needs.split(",") : [];
    el.innerHTML = needs.map((n) => {
      const ok = n === "lm" ? h.lm_studio : h.claude_cli;
      const name = n === "lm" ? "LM Studio" : "Claude CLI";
      return `<span class="req ${ok ? "on" : "off"}">${ok ? "✓" : "✗ 要"} ${name}</span>`;
    }).join("");
  });
}

// ---- ステップ3: 実行計画・進捗 ----
function renderPlan() {
  const nTasks = selectedTask ? 1 : S.tasks.length;
  const nArms = selectedArms.size;
  const reps = Number($("repeats").value);
  const total = nTasks * nArms * reps;
  $("plan").textContent = nArms === 0
    ? "実行計画: 条件を1つ以上選んでください"
    : `実行計画: タスク${nTasks}個 × 条件${nArms}個 × ${reps}回 = 合計 ${total} 回の実行`;
  $("run-btn").disabled = nArms === 0 || (S && S.job.running);
}

function renderJob() {
  const j = S.job;
  $("run-btn").hidden = j.running;
  $("stop-btn").hidden = !j.running;
  $("progress-wrap").hidden = !j.running && j.done === 0;
  if (j.total > 0) {
    const pct = Math.min(100, Math.round((j.done / j.total) * 100));
    $("bar-fill").style.width = pct + "%";
    $("progress-text").textContent = j.running
      ? `実行中… ${j.done} / ${j.total} 完了（クラウド実行は1回に数十秒〜数分かかります）`
      : `完了: ${j.done} / ${j.total}`;
  }
  const log = $("log-details");
  log.hidden = S.log.length === 0;
  const pre = $("log");
  const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 8;
  pre.textContent = S.log.join("\n");
  if (atBottom) pre.scrollTop = pre.scrollHeight;
}

// ---- 結果 ----
function renderResults() {
  $("n-runs").textContent = `（これまでの累計 ${S.n_runs} 回）`;
  const order = ["cloud_only", "router", "local_only", "mock"];
  $("report").tBodies[0].innerHTML = Object.entries(S.report)
    .sort(([a], [b]) => order.indexOf(a) - order.indexOf(b))
    .map(([arm, m]) => {
      const pct = Math.round(m.success_rate * 100);
      const info = ARM_INFO[arm];
      return `<tr>
        <td>${info ? info.title : arm}</td><td>${m.runs}</td>
        <td><div class="rate"><div class="rate-bar" style="width:${pct}%"></div><span>${pct}%</span></div></td>
        <td>${m.med_api_equiv_usd.toFixed(4)}</td>
        <td>${m.med_wall_s.toFixed(1)}</td>
        <td>${Math.round(m.med_out_tok)}</td>
        <td>${m.cloud_calls}回</td></tr>`;
    }).join("")
    || '<tr><td colspan="7" class="muted">まだ実行がありません。ステップ1〜3で最初のベンチを回してみてください。</td></tr>';

  const reg = S.regret;
  $("regret").hidden = !reg;
  if (reg) {
    $("regret").textContent =
      `オラクル regret: ルーター成功率 ${Math.round(reg.router_success_rate * 100)}% / ` +
      `全条件の結果を知る理想の振り分け（オラクル）${Math.round(reg.oracle_success_rate * 100)}% ` +
      `→ 差 ${Math.round(reg.regret * 100)}%（0%に近いほどルーターが賢い。対象 ${reg.pairs} 組）`;
  }

  $("recent").tBodies[0].innerHTML = S.recent.map((r) => `<tr>
    <td>${r.task}</td><td>${(ARM_INFO[r.arm] || { title: r.arm }).title}</td><td>${r.rep + 1}回目</td>
    <td class="${r.success ? "ok" : "ng"}">${r.success ? "成功" : "失敗"}${r.hit_cap ? "（上限超過）" : ""}</td>
    <td>${(r.api_equiv_usd ?? r.cost_usd).toFixed(4)}</td><td>${r.wall_s.toFixed(1)}</td>
    <td>${r.in_tok}</td><td>${r.out_tok}</td><td>${r.turns}</td></tr>`).join("")
    || '<tr><td colspan="9" class="muted">まだ実行がありません</td></tr>';
}

// ---- メインループ ----
async function refresh() {
  try {
    S = await (await fetch("/api/state")).json();
  } catch {
    $("env").innerHTML = '<span class="badge off">✗ サーバ停止中（ターミナルで python -m scripts.serve_ui）</span>';
    return;
  }
  if (!built) { buildTasks(); buildArms(); built = true; }
  renderEnv(); renderArmReqs(); renderPlan(); renderJob(); renderResults();
}

$("repeats").onchange = renderPlan;

$("run-btn").onclick = async () => {
  const arms = [...selectedArms];
  // クラウドを使う場合は消費の確認を挟む
  if (arms.includes("cloud_only") || arms.includes("router")) {
    if (!confirm("Claude（サブスク枠）を消費します。実行しますか？")) return;
  }
  const h = S.health;
  const needLm = arms.includes("local_only") || arms.includes("router");
  if (needLm && !h.lm_studio) {
    if (!confirm("LM Studio が起動していないようです。ローカル実行は失敗します。それでも実行しますか？")) return;
  }
  const res = await fetch("/api/bench", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ arms, repeats: Number($("repeats").value), task: selectedTask || null }),
  });
  if (!res.ok) alert((await res.json()).error);
  refresh();
};

$("stop-btn").onclick = async () => {
  await fetch("/api/stop", { method: "POST", body: "{}" });
  refresh();
};

refresh();
setInterval(refresh, 2000);
