import { jsxs as r, jsx as t } from "react/jsx-runtime";
import { useAppApi as N } from "@kirocrew/app-sdk";
import { Card as P, Btn as u, PageHeader as j } from "@kirocrew/app-sdk/ui";
import { useState as d, useCallback as C, useEffect as q } from "react";
function z() {
  return {
    spec: [],
    ready: [],
    todo: [],
    dev: [],
    review: [],
    review_ok: [],
    done: [],
    blocked: []
  };
}
function F(e) {
  return e < 60 ? `${e}m` : e < 1440 ? `${Math.floor(e / 60)}h` : `${Math.floor(e / 1440)}d`;
}
function K(e) {
  return e.split("/").pop() ?? e;
}
const m = {
  fontWeight: 400,
  fontSize: 15,
  opacity: 0.75,
  letterSpacing: "0.01em"
};
function y({ issue: e, showDispatch: n, onDispatch: l, dispatching: i }) {
  return /* @__PURE__ */ r(P, { style: { marginBottom: 8, padding: "10px 12px" }, children: [
    /* @__PURE__ */ r("div", { style: { display: "flex", alignItems: "flex-start", gap: 8 }, children: [
      /* @__PURE__ */ r("div", { style: { flex: 1, minWidth: 0 }, children: [
        /* @__PURE__ */ r("div", { style: { display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }, children: [
          /* @__PURE__ */ r("span", { style: { fontWeight: 600, fontSize: 12, opacity: 0.6, whiteSpace: "nowrap" }, children: [
            "#",
            e.number
          ] }),
          /* @__PURE__ */ t("span", { style: { fontWeight: 500, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }, children: e.title })
        ] }),
        /* @__PURE__ */ r("div", { style: { display: "flex", alignItems: "center", gap: 8, fontSize: 11, opacity: 0.6 }, children: [
          /* @__PURE__ */ t("span", { children: K(e.repo) }),
          e.age_min > 0 && /* @__PURE__ */ r("span", { children: [
            "⏱ ",
            F(e.age_min)
          ] }),
          e.running && /* @__PURE__ */ t("span", { style: { color: "#f97316" }, children: "● running" })
        ] })
      ] }),
      n && l && /* @__PURE__ */ t(
        u,
        {
          size: "sm",
          variant: "secondary",
          disabled: i,
          onClick: () => l(e.repo, e.number),
          style: { flexShrink: 0, fontSize: 11 },
          children: i ? "..." : "Dispatch"
        }
      )
    ] }),
    e.url && /* @__PURE__ */ t(
      "a",
      {
        href: e.url,
        target: "_blank",
        rel: "noreferrer",
        style: { fontSize: 11, opacity: 0.5, textDecoration: "none", display: "block", marginTop: 4 },
        children: "🔗 Ver issue"
      }
    )
  ] });
}
const U = {
  flex: 1,
  minWidth: 380,
  border: "1px solid rgba(128,128,128,0.25)",
  borderRadius: 10,
  padding: "14px 16px",
  background: "rgba(128,128,128,0.04)"
}, O = {
  fontSize: 12,
  opacity: 0.4,
  textAlign: "center",
  padding: "20px 0"
};
function _({ title: e, issues: n }) {
  return /* @__PURE__ */ r("div", { style: U, children: [
    /* @__PURE__ */ r("div", { style: { display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }, children: [
      /* @__PURE__ */ t("span", { style: m, children: e }),
      /* @__PURE__ */ r("span", { style: { fontSize: 12, opacity: 0.5 }, children: [
        "(",
        n.length,
        ")"
      ] })
    ] }),
    n.length === 0 ? /* @__PURE__ */ t("div", { style: O, children: "Nenhuma issue aguardando" }) : n.map((l) => /* @__PURE__ */ t(y, { issue: l }, `${l.repo}#${l.number}`))
  ] });
}
function H({ columns: e }) {
  return /* @__PURE__ */ r("div", { style: { display: "flex", gap: 16, marginTop: 20, flexWrap: "wrap" }, children: [
    /* @__PURE__ */ t(_, { title: "Aguardando SPEC", issues: e.spec }),
    /* @__PURE__ */ t(_, { title: "Aguardando definição de produto/TL", issues: e.ready })
  ] });
}
const Q = {
  flex: 1,
  minWidth: 200
}, V = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  marginBottom: 10,
  fontSize: 12,
  textTransform: "uppercase",
  letterSpacing: "0.04em",
  opacity: 0.7
}, G = {
  fontSize: 12,
  opacity: 0.4,
  textAlign: "center",
  padding: "16px 0"
};
function f({ title: e, issues: n, showDispatch: l, onDispatch: i, dispatchingKey: s }) {
  return /* @__PURE__ */ r("div", { style: Q, children: [
    /* @__PURE__ */ r("div", { style: V, children: [
      /* @__PURE__ */ t("span", { children: e }),
      /* @__PURE__ */ r("span", { style: { opacity: 0.6 }, children: [
        "(",
        n.length,
        ")"
      ] })
    ] }),
    n.length === 0 ? /* @__PURE__ */ t("div", { style: G, children: "—" }) : n.map((o) => {
      const g = `${o.repo}#${o.number}`;
      return /* @__PURE__ */ t(
        y,
        {
          issue: o,
          showDispatch: l,
          onDispatch: i,
          dispatching: s === g
        },
        g
      );
    })
  ] });
}
function $({ title: e, children: n }) {
  return /* @__PURE__ */ r(
    "div",
    {
      style: {
        flex: 1,
        minWidth: 440,
        border: "1px solid rgba(128,128,128,0.25)",
        borderRadius: 10,
        padding: "14px 16px",
        background: "rgba(128,128,128,0.04)"
      },
      children: [
        /* @__PURE__ */ t("div", { style: { ...m, marginBottom: 12 }, children: e }),
        /* @__PURE__ */ t("div", { style: { display: "flex", gap: 12 }, children: n })
      ]
    }
  );
}
function A({ title: e, issues: n, color: l }) {
  return n.length === 0 ? null : /* @__PURE__ */ r("div", { style: { flex: 1, minWidth: 260 }, children: [
    /* @__PURE__ */ r(
      "div",
      {
        style: {
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 8,
          paddingBottom: 6,
          borderBottom: `2px solid ${l}`
        },
        children: [
          /* @__PURE__ */ t("span", { style: { fontWeight: 700, fontSize: 12, textTransform: "uppercase", letterSpacing: "0.04em" }, children: e }),
          /* @__PURE__ */ t(
            "span",
            {
              style: {
                background: l,
                color: "#fff",
                borderRadius: 10,
                padding: "1px 7px",
                fontSize: 11,
                fontWeight: 700
              },
              children: n.length
            }
          )
        ]
      }
    ),
    n.map((i) => /* @__PURE__ */ t(y, { issue: i }, `${i.repo}#${i.number}`))
  ] });
}
function J({ columns: e, onDispatch: n, dispatchingKey: l }) {
  const i = e.review.filter((o) => !o.running), s = e.review.filter((o) => o.running);
  return /* @__PURE__ */ r("div", { style: { marginTop: 24 }, children: [
    /* @__PURE__ */ t("div", { style: { ...m, fontSize: 18, marginBottom: 14 }, children: "Agentes" }),
    /* @__PURE__ */ r("div", { style: { display: "flex", gap: 16, flexWrap: "wrap" }, children: [
      /* @__PURE__ */ r($, { title: "Desenvolvimento", children: [
        /* @__PURE__ */ t(
          f,
          {
            title: "Aguardando",
            issues: e.todo,
            showDispatch: !0,
            onDispatch: n,
            dispatchingKey: l
          }
        ),
        /* @__PURE__ */ t(f, { title: "Trabalhando", issues: e.dev })
      ] }),
      /* @__PURE__ */ r($, { title: "Code Review", children: [
        /* @__PURE__ */ t(f, { title: "Aguardando", issues: i }),
        /* @__PURE__ */ t(f, { title: "Trabalhando", issues: s })
      ] })
    ] }),
    (e.review_ok.length > 0 || e.blocked.length > 0) && /* @__PURE__ */ r("div", { style: { display: "flex", gap: 16, marginTop: 20, flexWrap: "wrap" }, children: [
      /* @__PURE__ */ t(A, { title: "Aguardando merge", issues: e.review_ok, color: "#0ea5e9" }),
      /* @__PURE__ */ t(A, { title: "Blocked", issues: e.blocked, color: "#dc2626" })
    ] })
  ] });
}
const X = {
  spec: [
    { number: 97, title: "Exemplo: issue aguardando SPEC", repo: "eliasrosa/kirocrew-flow", url: "", age_min: 15, labels: ["crewflow:spec"], blocked: !1, running: !1 }
  ],
  ready: [
    { number: 98, title: "Exemplo: aguardando definição de produto/TL", repo: "eliasrosa/kirocrew-flow", url: "", age_min: 60, labels: ["crewflow:ready"], blocked: !1, running: !1 }
  ],
  todo: [
    { number: 99, title: "Exemplo: feature aguardando dev", repo: "eliasrosa/kirocrew-flow", url: "", age_min: 45, labels: ["crewflow:feature", "crewflow:p2"], blocked: !1, running: !1 }
  ],
  dev: [
    { number: 100, title: "Exemplo: issue em implementação", repo: "eliasrosa/kirocrew-flow", url: "", age_min: 120, labels: ["crewflow:bug", "crewflow:p1"], blocked: !1, running: !0 }
  ],
  review: [
    { number: 101, title: "Exemplo: PR aguardando review", repo: "eliasrosa/kirocrew-flow", url: "", age_min: 30, labels: ["crewflow:feature"], blocked: !1, running: !1 }
  ],
  review_ok: [
    { number: 103, title: "Exemplo: aprovado, aguardando merge", repo: "eliasrosa/kirocrew-flow", url: "", age_min: 10, labels: ["crewflow:review-ok"], blocked: !1, running: !1 }
  ],
  done: [],
  blocked: [
    { number: 102, title: "Exemplo: issue bloqueada", repo: "eliasrosa/kirocrew-flow", url: "", age_min: 240, labels: ["crewflow:debt"], blocked: !0, running: !1 }
  ]
}, Y = "KiroCrew Flow";
function re() {
  const e = N(), [n, l] = d(z()), [i, s] = d(""), [o, g] = d(""), [w, W] = d(!0), [b, h] = d(null), [E, v] = d(!1), [x, T] = d(null), [B, k] = d(null), c = C(() => e.get("/api/apps/kirocrew-flow/issues").then((a) => {
    l(a.columns ?? z()), s(a.squad_name ?? ""), g(a.project ?? ""), T(/* @__PURE__ */ new Date()), h(null), v(!1);
  }).catch((a) => {
    const p = String(a);
    p.includes("404") || p.includes("not found") ? (l(X), s(""), g(""), v(!0), h(null)) : h(p);
  }).finally(() => {
    W(!1);
  }), [e]);
  q(() => {
    c();
    const a = setInterval(c, 15e3);
    return () => clearInterval(a);
  }, [c]);
  const I = C(
    async (a, p) => {
      const M = `${a}#${p}`;
      k(M);
      try {
        await e.post("/api/apps/kirocrew-flow/dispatch", { repo: a, number: Number(p) }), await c();
      } catch (R) {
        console.error("dispatch failed:", R);
      } finally {
        k(null);
      }
    },
    [e, c]
  ), S = i || Y, D = o ? `Flow - ${S} / ${o}` : `Flow - ${S}`, L = n.spec.length + n.ready.length + n.todo.length + n.dev.length + n.review.length + n.review_ok.length + n.blocked.length;
  return /* @__PURE__ */ r("div", { style: { padding: "20px 24px", maxWidth: 1400 }, children: [
    /* @__PURE__ */ t(
      j,
      {
        title: D,
        subtitle: w ? "Carregando…" : b ? `Erro: ${b}` : E ? "⚠️ Modo demo — backend indisponível (issue #170)" : x ? `${L} issues ativas · atualizado ${x.toLocaleTimeString()}` : "",
        actions: /* @__PURE__ */ r("div", { style: { display: "flex", gap: 8 }, children: [
          /* @__PURE__ */ t(u, { size: "sm", variant: "secondary", onClick: () => console.log("Configurações (placeholder)"), children: "Configurações" }),
          /* @__PURE__ */ t(u, { size: "sm", variant: "secondary", onClick: () => console.log("Rules (placeholder)"), children: "Rules" }),
          /* @__PURE__ */ t(u, { size: "sm", variant: "secondary", onClick: c, disabled: w, children: "↻ Atualizar" })
        ] })
      }
    ),
    /* @__PURE__ */ t(H, { columns: n }),
    /* @__PURE__ */ t(J, { columns: n, onDispatch: I, dispatchingKey: B ?? void 0 })
  ] });
}
export {
  re as default
};
