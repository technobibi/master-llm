// 2秒ごとに /api/state を取得して全セクションを描き直すだけの素朴な構成。
const $ = (id) => document.getElementById(id);
let armsInit = false;

async function refresh() {
  let s;
  try {
    s = await (await fetch("/api/state")).json();
  } catch {
    $("status").textContent = "サーバ停止?";
    return;
  }

  // 状態バッジとボタン
  $("status").textContent = s.running ? "実行中…" : "待機中";
  $("status").className = "badge " + (s.running ? "run" : "idle");
  $("run-btn").disabled = s.running;
  $("stop-btn").disabled = !s.running;

  // arm チェックボックスとタスク選択（初回のみ生成）
  if (!armsInit) {
    $("arm-boxes").innerHTML = s.arms.map((a) =>
      `<label><input type="checkbox" value="${a}" ${a === "mock" ? "checked" : ""}>${a}</label>`
    ).join("");
    $("task-select").innerHTML = '<option value="">すべて</option>' +
      s.tasks.map((t) => `<option value="${t.id}">${t.id}</option>`).join("");
    armsInit = true;
  }

  // 実行ログ
  const log = $("log");
  log.hidden = s.log.length === 0;
  const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 8;
  log.textContent = s.log.join("\n");
  if (atBottom) log.scrollTop = log.scrollHeight;

  // 集計テーブル
  $("n-runs").textContent = `全 ${s.n_runs} run`;
  $("report").tBodies[0].innerHTML = Object.entries(s.report)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([arm, m]) => `<tr>
      <td>${arm}</td><td>${m.runs}</td>
      <td>${Math.round(m.success_rate * 100)}%</td>
      <td>${m.avg_cost_usd.toFixed(4)}</td>
      <td>${m.avg_wall_s.toFixed(1)}</td>
      <td>${Math.round(m.avg_out_tok)}</td></tr>`).join("")
    || '<tr><td colspan="6" class="muted">まだ実行がありません</td></tr>';

  // 履歴テーブル
  $("recent").tBodies[0].innerHTML = s.recent.map((r) => `<tr>
    <td>${r.task}</td><td>${r.arm}</td><td>${r.rep}</td>
    <td class="${r.success ? "ok" : "ng"}">${r.success ? "成功" : "失敗"}${r.hit_cap ? " (cap)" : ""}</td>
    <td>${r.cost_usd.toFixed(4)}</td><td>${r.wall_s.toFixed(1)}</td>
    <td>${r.in_tok}</td><td>${r.out_tok}</td><td>${r.turns}</td></tr>`).join("")
    || '<tr><td colspan="9" class="muted">まだ実行がありません</td></tr>';

  // タスクカード
  $("task-cards").innerHTML = s.tasks.map((t) => `<div class="card">
    <div class="meta"><b>${t.id}</b> ｜ ${t.category} ｜ 対象: ${t.target_file}
      ｜ 上限: $${t.budget.max_cost_usd} / ${t.budget.max_turns}turns / ${t.budget.max_wall_s}s</div>
    <pre>${t.prompt.replace(/</g, "&lt;")}</pre></div>`).join("");
}

$("run-btn").onclick = async () => {
  const arms = [...document.querySelectorAll("#arm-boxes input:checked")].map((x) => x.value);
  const body = {
    arms,
    repeats: Number($("repeats").value) || 1,
    task: $("task-select").value || null,
  };
  const res = await fetch("/api/bench", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
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
