"use strict";
const notice = document.getElementById("notice");
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
    location.assign(new URLSearchParams(location.search).get("next") === "activate" ? "/activate" : "/admin/");
  } catch (error) { notice.textContent = error.message; }
});
const logout = document.getElementById("logout");
if (logout) logout.addEventListener("click", async () => {
  try { await api("/admin/logout", {}); location.assign("/admin/login"); }
  catch (error) { notice.textContent = error.message; }
});
