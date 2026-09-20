import { jsxs as n, jsx as t } from "react/jsx-runtime";
import { useAppApi as a } from "@kirocrew/app-sdk";
import { PageHeader as m, StatCard as f, Card as h, Btn as v } from "@kirocrew/app-sdk/ui";
import { useState as w, useEffect as y } from "react";
const b = ["todo", "dev", "review", "reviewed", "done"], x = {
  todo: "To Do",
  dev: "Dev",
  review: "Review",
  reviewed: "Reviewed",
  done: "Done",
  blocked: "Blocked"
};
function C(o) {
  if (o == null || Number.isNaN(o)) return "—";
  if (o < 60) return `${Math.round(o)}m`;
  const r = o / 60;
  if (r < 24) return `${Math.round(r)}h`;
  const l = r / 24;
  return `${Math.round(l)}d`;
}
function D() {
  const o = a(), [r, l] = w({}), d = () => o.get("/api/apps/kirocrew-flow/issues").then((e) => l(e.columns || {}));
  y(() => {
    d();
    const e = setInterval(d, 15e3);
    return () => clearInterval(e);
  }, []);
  const c = (e) => o.post("/api/apps/kirocrew-flow/dispatch", { repo: e.repo, number: e.number }).then(d), p = (e, i) => /* @__PURE__ */ n(h, { children: [
    /* @__PURE__ */ n("div", { style: { fontWeight: 600 }, children: [
      "#",
      e.number,
      " ",
      e.title
    ] }),
    /* @__PURE__ */ t("div", { style: { fontSize: 12, opacity: 0.7 }, children: e.repo }),
    /* @__PURE__ */ n("div", { style: { fontSize: 12, opacity: 0.7 }, children: [
      "em estágio: ",
      C(e.age_min)
    ] }),
    i === "todo" && /* @__PURE__ */ t("div", { style: { marginTop: 8 }, children: /* @__PURE__ */ t(v, { onClick: () => c(e), children: "force dispatch" }) })
  ] }, `${e.repo}#${e.number}`), s = (e) => {
    const i = r[e] || [];
    return /* @__PURE__ */ n("div", { style: { minWidth: 220, flex: 1 }, children: [
      /* @__PURE__ */ t(f, { label: x[e] ?? e, value: i.length }),
      /* @__PURE__ */ t("div", { style: { display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }, children: i.map((u) => p(u, e)) })
    ] }, e);
  };
  return /* @__PURE__ */ n("div", { children: [
    /* @__PURE__ */ t(m, { title: "KiroCrew Flow" }),
    /* @__PURE__ */ t("div", { style: { display: "flex", gap: 16, alignItems: "flex-start", overflowX: "auto" }, children: b.map((e) => s(e)) }),
    /* @__PURE__ */ t("div", { style: { marginTop: 24 }, children: s("blocked") })
  ] });
}
export {
  D as default
};
