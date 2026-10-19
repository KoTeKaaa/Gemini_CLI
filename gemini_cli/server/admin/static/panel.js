"use strict";
const notice = document.getElementById("notice");
const activation = document.getElementById("activation");
let activationToken = activation ? location.hash.slice(1) : "";
const confirmationForm = document.getElementById("account-confirmation");
let confirmation = confirmationForm ? Object.fromEntries(new URLSearchParams(location.hash.slice(1))) : {};
if (activation || confirmationForm) history.replaceState(null, "", location.pathname);
async function activationIdentity() {
  const response = await fetch("/activation/session", {cache: "no-store"});
  if (!response.ok) { activation.hidden = true; login.hidden = false; return; }
  const account = await response.json();
  document.getElementById("activation-account").textContent = account.user_id;
  activation.hidden = false; login.hidden = true;
}
async function api(path, data, method = "POST") {
  const session = await fetch("/admin/session", {cache: "no-store"}).then(r => r.json());
  const response = await fetch(path, {method, headers: {"Content-Type": "application/json",
    "X-CSRF-Token": session.csrf}, body: JSON.stringify(path === "/admin/login" ? {...data, csrf: session.csrf} : data)});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Проверьте введённые данные");
  return result;
}
const login = document.getElementById("login");
if (login) login.addEventListener("submit", async event => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(login));
  try {
    await api("/admin/login", values);
    login.reset();
    if (activation) await activationIdentity();
    else location.assign("/admin/");
  } catch (error) { notice.textContent = error.message; }
});
const logout = document.getElementById("logout");
if (logout) logout.addEventListener("click", async () => {
  try {
    await api("/admin/logout", {});
    if (activation) { activation.hidden = true; login.hidden = false; }
    else location.assign("/admin/login");
  }
  catch (error) { notice.textContent = error.message; }
});
const subscription = document.getElementById("subscription");
if (subscription) {
  subscription.addEventListener("submit", async event => {
    event.preventDefault();
    const form = new FormData(subscription);
    const id = form.get("id");
    const data = {user_id: form.get("user_id") || null, status: form.get("status"),
      expires_at: new Date(form.get("expires_at")).toISOString(),
      models: form.getAll("models"), features: form.getAll("features"),
      request_limit: Number(form.get("request_limit")), window_seconds: Number(form.get("window_seconds")),
      parallel_limit: Number(form.get("parallel_limit"))};
    if (id) data.rights_version = Number(form.get("rights_version"));
    if (data.status === "revoked" && !confirm("Отозвать доступ? Новые запросы и продолжения будут запрещены. Уже начатые вызовы могут завершиться.")) return;
    try { await api("/admin/api/subscriptions" + (id ? "/" + id : ""), data, id ? "PUT" : "POST"); location.reload(); }
    catch (error) { notice.textContent = error.message; }
  });
  document.getElementById("new-subscription").addEventListener("click", () => {
    subscription.reset(); subscription.elements.id.value = "";
    subscription.elements.rights_version.value = ""; subscription.elements.user_id.readOnly = false;
    document.getElementById("form-title").textContent = "Новая подписка";
  });
  for (const button of document.querySelectorAll("[data-edit]")) button.addEventListener("click", () => {
    const row = JSON.parse(button.dataset.edit);
    for (const name of ["id", "rights_version", "status", "request_limit", "window_seconds", "parallel_limit"])
      subscription.elements[name].value = row[name];
    subscription.elements.user_id.value = row.user_id || "";
    subscription.elements.user_id.readOnly = true;
    const date = new Date(row.expires_at);
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    subscription.elements.expires_at.value = local.toISOString().slice(0, 16);
    for (const name of ["models", "features"])
      for (const option of subscription.elements[name].options) option.selected = row[name].includes(option.value);
    document.getElementById("form-title").textContent = "Изменить подписку · версия " + row.rights_version;
    subscription.scrollIntoView({behavior: "smooth"});
  });
}
for (const button of document.querySelectorAll("[data-invite]")) button.addEventListener("click", async () => {
  if (!confirm("Выпустить ссылку на 24 часа? Предыдущая неиспользованная ссылка будет отозвана.")) return;
  try {
    const result = await api("/admin/api/invitations", {subscription_id: button.dataset.invite});
    document.getElementById("invitation-url").value = result.url;
    document.getElementById("invitation-result").hidden = false;
    document.getElementById("invitation-result").scrollIntoView();
  } catch (error) { notice.textContent = error.message; }
});
const copy = document.getElementById("copy-invitation");
if (copy) copy.addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(document.getElementById("invitation-url").value); notice.textContent = "Ссылка скопирована"; }
  catch { notice.textContent = "Выделите и скопируйте ссылку вручную"; }
});
const accountInvitation = document.getElementById("account-invitation");
if (accountInvitation) accountInvitation.addEventListener("submit", async event => {
  event.preventDefault();
  try { notice.textContent = (await api("/admin/api/accounts/invite", Object.fromEntries(new FormData(accountInvitation)))).detail; }
  catch (error) { notice.textContent = error.message; }
});
if (activation) {
  activationIdentity().catch(() => { notice.textContent = "Не удалось проверить вход. Повторите попытку."; });
  document.getElementById("activate-access").addEventListener("click", async () => {
    if (!activationToken) { notice.textContent = "Откройте исходную ссылку приглашения снова."; return; }
    try {
      await api("/activate", {token: activationToken});
      activationToken = "";
      document.getElementById("activate-access").disabled = true;
      notice.textContent = "Доступ активирован. Теперь войдите в этот аккаунт в CLI.";
    } catch (error) { notice.textContent = error.message; }
  });
}
if (confirmationForm) confirmationForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (!confirmation.access_token || !confirmation.refresh_token) {
    notice.textContent = "Откройте действующую ссылку из письма приглашения."; return;
  }
  try {
    const result = await api("/account/confirm", {access_token: confirmation.access_token,
      refresh_token: confirmation.refresh_token, password: new FormData(confirmationForm).get("password")});
    confirmation = {}; confirmationForm.reset(); confirmationForm.hidden = true;
    notice.textContent = result.detail;
  } catch (error) { notice.textContent = error.message; }
});
