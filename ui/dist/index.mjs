import { jsxs as t, jsx as r } from "react/jsx-runtime";
import { useAppApi as P } from "@kirocrew/app-sdk";
import { PageHeader as Q, Btn as b, Card as j } from "@kirocrew/app-sdk/ui";
import { useState as p, useCallback as _, useEffect as L } from "react";
function N(e) {
  return e < 60 ? `${e}m` : e < 1440 ? `${Math.floor(e / 60)}h` : `${Math.floor(e / 1440)}d`;
}
function F(e) {
  return e.split("/").pop() ?? e;
}
function z() {
  return {
    spec: [],
    ready: [],
    todo: [],
    dev: [],
    review: [],
    review_ok: [],
    reviewed: [],
    qa: [],
    qa_fail: [],
    done: [],
    blocked: []
  };
}
const O = {
  squad_name: "KiroCrew Flow (demo)",
  project: "eliasrosa/kirocrew-flow",
  columns: {
    spec: [
      { number: 95, title: "Exemplo: feature sendo especificada", repo: "eliasrosa/kirocrew-flow", url: "", age_min: 240, labels: ["crewflow:spec", "crewflow:feature"], blocked: !1, running: !1 }
    ],
    ready: [
      { number: 97, title: "Exemplo: spec pronta, aguardando priorização", repo: "eliasrosa/kirocrew-flow", url: "", age_min: 120, labels: ["crewflow:ready", "crewflow:feature"], blocked: !1, running: !1 }
    ],
    todo: [
      { number: 99, title: "Exemplo: feature aguardando dev", repo: "eliasrosa/kirocrew-flow", url: "", age_min: 45, labels: ["crewflow:feature", "crewflow:p2"], blocked: !1, running: !1 }
    ],
    dev: [
      { number: 100, title: "Exemplo: issue em implementação", repo: "eliasrosa/kirocrew-flow", url: "", age_min: 120, labels: ["crewflow:bug", "crewflow:p1"], blocked: !1, running: !0 },
      { number: 104, title: "Exemplo: divergência — label=dev mas sem branch", repo: "eliasrosa/kirocrew-flow", url: "", age_min: 30, labels: ["crewflow:feature"], blocked: !1, running: !1, implicit_state: "todo" }
    ],
    review: [
      { number: 101, title: "Exemplo: PR aguardando review", repo: "eliasrosa/kirocrew-flow", url: "", age_min: 30, labels: ["crewflow:feature"], blocked: !1, running: !1, implicit_state: "review" }
    ],
    review_ok: [
      { number: 103, title: "Exemplo: PR aprovado, aguardando merge", repo: "eliasrosa/kirocrew-flow", url: "", age_min: 15, labels: ["crewflow:feature", "crewflow:review-ok"], blocked: !1, running: !1 }
    ],
    reviewed: [],
    qa: [
      { number: 105, title: "Exemplo: issue em teste de QA", repo: "eliasrosa/kirocrew-flow", url: "", age_min: 20, labels: ["crewflow:qa", "crewflow:feature"], blocked: !1, running: !1 }
    ],
    qa_fail: [
      { number: 106, title: "Exemplo: QA reprovado, aguardando volta ao dev", repo: "eliasrosa/kirocrew-flow", url: "", age_min: 10, labels: ["crewflow:qa-fail", "crewflow:bug"], blocked: !1, running: !1 }
    ],
    done: [],
    blocked: [
      { number: 102, title: "Exemplo: issue bloqueada", repo: "eliasrosa/kirocrew-flow", url: "", age_min: 240, labels: ["crewflow:debt"], blocked: !0, running: !1 }
    ]
  }
}, U = {
  todo: "todo",
  dev: "dev",
  review: "review",
  reviewed: "review",
  // QA está na coluna reviewed; implicit equivalente é review/review_ok
  done: "done",
  blocked: ""
};
function H(e, i) {
  if (!e.implicit_state) return !1;
  const o = U[i] ?? "";
  return !o || i === "review" && e.implicit_state === "review_ok" ? !1 : e.implicit_state !== o;
}
function W({ issue: e, showDispatch: i, onDispatch: o, dispatching: a, column: n = "", showQaActions: f, onQaFail: g, onQaApprove: m, qaBusy: u }) {
  const h = H(e, n);
  return /* @__PURE__ */ t(j, { style: { marginBottom: 8, padding: "10px 12px" }, children: [
    /* @__PURE__ */ t("div", { style: { display: "flex", alignItems: "flex-start", gap: 8 }, children: [
      /* @__PURE__ */ t("div", { style: { flex: 1, minWidth: 0 }, children: [
        /* @__PURE__ */ t("div", { style: { display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }, children: [
          /* @__PURE__ */ t("span", { style: { fontWeight: 600, fontSize: 12, opacity: 0.6, whiteSpace: "nowrap" }, children: [
            "#",
            e.number
          ] }),
          /* @__PURE__ */ r("span", { style: { fontWeight: 500, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }, children: e.title })
        ] }),
        /* @__PURE__ */ t("div", { style: { display: "flex", alignItems: "center", gap: 8, fontSize: 11, opacity: 0.6 }, children: [
          /* @__PURE__ */ r("span", { children: F(e.repo) }),
          e.age_min > 0 && /* @__PURE__ */ t("span", { children: [
            "⏱ ",
            N(e.age_min)
          ] }),
          e.running && /* @__PURE__ */ r("span", { style: { color: "#f97316" }, children: "● running" }),
          h && e.implicit_state && /* @__PURE__ */ t(
            "span",
            {
              title: `Estado implícito: ${e.implicit_state} · Label atual: ${n}`,
              style: {
                color: "#dc2626",
                fontWeight: 700,
                background: "#fee2e2",
                borderRadius: 4,
                padding: "1px 5px",
                fontSize: 10,
                letterSpacing: "0.02em"
              },
              children: [
                "⚠ impl: ",
                e.implicit_state
              ]
            }
          )
        ] })
      ] }),
      i && o && /* @__PURE__ */ r(
        b,
        {
          size: "sm",
          variant: "secondary",
          disabled: a,
          onClick: () => o(e.repo, e.number),
          style: { flexShrink: 0, fontSize: 11 },
          children: a ? "..." : "Dispatch"
        }
      ),
      f && (g || m) && /* @__PURE__ */ t("div", { style: { display: "flex", flexDirection: "column", gap: 4, flexShrink: 0 }, children: [
        m && /* @__PURE__ */ r(
          b,
          {
            size: "sm",
            variant: "secondary",
            disabled: u,
            onClick: () => m(e.repo, e.number),
            style: { fontSize: 11 },
            children: u ? "..." : "Aprovar QA"
          }
        ),
        g && /* @__PURE__ */ r(
          b,
          {
            size: "sm",
            variant: "secondary",
            disabled: u,
            onClick: () => g(e.repo, e.number),
            style: { fontSize: 11 },
            children: u ? "..." : "Reprovar QA"
          }
        )
      ] })
    ] }),
    e.url && /* @__PURE__ */ r(
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
function y({ title: e, issues: i, color: o, showDispatch: a, onDispatch: n, dispatchingKey: f, columnKey: g = "", showQaActions: m, onQaFail: u, onQaApprove: h, qaBusyKey: v }) {
  return /* @__PURE__ */ t("div", { style: { flex: 1, minWidth: 160 }, children: [
    /* @__PURE__ */ t("div", { style: {
      fontSize: 11,
      fontWeight: 600,
      textTransform: "uppercase",
      letterSpacing: "0.06em",
      opacity: 0.55,
      marginBottom: 8,
      paddingBottom: 4,
      borderBottom: `1px solid ${o}44`,
      display: "flex",
      alignItems: "center",
      gap: 6
    }, children: [
      e,
      /* @__PURE__ */ r("span", { style: {
        background: o + "33",
        color: o,
        borderRadius: 8,
        padding: "0 6px",
        fontSize: 10,
        fontWeight: 700
      }, children: i.length })
    ] }),
    i.length === 0 ? /* @__PURE__ */ r("div", { style: { fontSize: 12, opacity: 0.3, textAlign: "center", padding: "12px 0" }, children: "—" }) : i.map((x) => {
      const w = `${x.repo}#${x.number}`;
      return /* @__PURE__ */ r(
        W,
        {
          issue: x,
          showDispatch: a,
          onDispatch: n,
          dispatching: f === w,
          column: g,
          showQaActions: m,
          onQaFail: u,
          onQaApprove: h,
          qaBusy: v === w
        },
        w
      );
    })
  ] });
}
function A({ title: e, subtitle: i, issues: o, accentColor: a }) {
  return /* @__PURE__ */ t("div", { style: {
    flex: 1,
    border: `1px solid ${a}33`,
    borderRadius: 10,
    padding: "14px 16px",
    background: `${a}08`,
    minWidth: 220
  }, children: [
    /* @__PURE__ */ t("div", { style: { marginBottom: 10 }, children: [
      /* @__PURE__ */ r("div", { style: { fontWeight: 700, fontSize: 13, color: a, marginBottom: 2 }, children: e }),
      /* @__PURE__ */ r("div", { style: { fontSize: 11, opacity: 0.5 }, children: i })
    ] }),
    o.length === 0 ? /* @__PURE__ */ r("div", { style: { fontSize: 12, opacity: 0.3, textAlign: "center", padding: "12px 0" }, children: "—" }) : o.map((n) => /* @__PURE__ */ r(W, { issue: n }, `${n.repo}#${n.number}`))
  ] });
}
function V({ columns: e, onDispatch: i, dispatchingKey: o, onQaFail: a, onQaApprove: n, qaBusyKey: f }) {
  return /* @__PURE__ */ t("div", { style: {
    border: "1px solid rgba(128,128,128,0.15)",
    borderRadius: 10,
    padding: "14px 16px",
    marginTop: 16
  }, children: [
    /* @__PURE__ */ r("div", { style: { fontWeight: 700, fontSize: 12, opacity: 0.4, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 14 }, children: "Agentes" }),
    /* @__PURE__ */ t("div", { style: { display: "flex", gap: 20, flexWrap: "wrap" }, children: [
      /* @__PURE__ */ t("div", { style: { flex: 1, minWidth: 300 }, children: [
        /* @__PURE__ */ t("div", { style: {
          fontWeight: 700,
          fontSize: 13,
          marginBottom: 12,
          paddingBottom: 6,
          borderBottom: "2px solid #2563eb",
          display: "flex",
          alignItems: "center",
          gap: 8
        }, children: [
          /* @__PURE__ */ r("span", { children: "Desenvolvimento" }),
          /* @__PURE__ */ r("span", { style: {
            background: "#2563eb",
            color: "#fff",
            borderRadius: 10,
            padding: "1px 7px",
            fontSize: 11,
            fontWeight: 700
          }, children: e.todo.length + e.dev.length })
        ] }),
        /* @__PURE__ */ t("div", { style: { display: "flex", gap: 12 }, children: [
          /* @__PURE__ */ r(
            y,
            {
              title: "Aguardando",
              issues: e.todo,
              color: "#16a34a",
              showDispatch: !0,
              onDispatch: i,
              dispatchingKey: o ?? void 0,
              columnKey: "todo"
            }
          ),
          /* @__PURE__ */ r(
            y,
            {
              title: "Trabalhando",
              issues: e.dev,
              color: "#2563eb",
              columnKey: "dev"
            }
          )
        ] })
      ] }),
      /* @__PURE__ */ t("div", { style: { flex: 1, minWidth: 300 }, children: [
        /* @__PURE__ */ t("div", { style: {
          fontWeight: 700,
          fontSize: 13,
          marginBottom: 12,
          paddingBottom: 6,
          borderBottom: "2px solid #8b5cf6",
          display: "flex",
          alignItems: "center",
          gap: 8
        }, children: [
          /* @__PURE__ */ r("span", { children: "Code Review" }),
          /* @__PURE__ */ r("span", { style: {
            background: "#8b5cf6",
            color: "#fff",
            borderRadius: 10,
            padding: "1px 7px",
            fontSize: 11,
            fontWeight: 700
          }, children: e.review.length + e.review_ok.length })
        ] }),
        /* @__PURE__ */ t("div", { style: { display: "flex", gap: 12 }, children: [
          /* @__PURE__ */ r(
            y,
            {
              title: "Aguardando",
              issues: e.review,
              color: "#8b5cf6",
              columnKey: "review"
            }
          ),
          /* @__PURE__ */ r(
            y,
            {
              title: "Aprovado ✓",
              issues: e.review_ok,
              color: "#22c55e",
              columnKey: "review_ok"
            }
          )
        ] })
      ] }),
      /* @__PURE__ */ t("div", { style: { flex: 1, minWidth: 300 }, children: [
        /* @__PURE__ */ t("div", { style: {
          fontWeight: 700,
          fontSize: 13,
          marginBottom: 12,
          paddingBottom: 6,
          borderBottom: "2px solid #0ea5e9",
          display: "flex",
          alignItems: "center",
          gap: 8
        }, children: [
          /* @__PURE__ */ r("span", { children: "QA" }),
          /* @__PURE__ */ r("span", { style: {
            background: "#0ea5e9",
            color: "#fff",
            borderRadius: 10,
            padding: "1px 7px",
            fontSize: 11,
            fontWeight: 700
          }, children: e.qa.length + e.qa_fail.length })
        ] }),
        /* @__PURE__ */ t("div", { style: { display: "flex", gap: 12 }, children: [
          /* @__PURE__ */ r(
            y,
            {
              title: "Em teste",
              issues: e.qa,
              color: "#0ea5e9",
              columnKey: "qa",
              showQaActions: !0,
              onQaFail: a,
              onQaApprove: n,
              qaBusyKey: f ?? void 0
            }
          ),
          /* @__PURE__ */ r(
            y,
            {
              title: "Reprovado",
              issues: e.qa_fail,
              color: "#dc2626",
              columnKey: "qa_fail"
            }
          )
        ] })
      ] })
    ] })
  ] });
}
function Z() {
  const e = P(), [i, o] = p(z()), [a, n] = p("KiroCrew Flow"), [f, g] = p(""), [m, u] = p(!0), [h, v] = p(null), [x, w] = p(!1), [q, B] = p(null), [C, $] = p(null), [E, S] = p(null), s = _(() => e.get("/api/apps/kirocrew-flow/issues").then((l) => {
    o(l.columns ?? z()), n(l.squad_name || "KiroCrew Flow"), g(l.project || ""), B(/* @__PURE__ */ new Date()), v(null), w(!1);
  }).catch((l) => {
    const d = String(l);
    if (d.includes("404") || d.includes("not found")) {
      const c = O;
      o(c.columns ?? z()), n(c.squad_name), g(c.project), w(!0), v(null);
    } else
      v(d);
  }).finally(() => {
    u(!1);
  }), [e]);
  L(() => {
    s();
    const l = setInterval(s, 15e3);
    return () => clearInterval(l);
  }, [s]);
  const K = _(
    async (l, d) => {
      const c = `${l}#${d}`;
      $(c);
      try {
        await e.post("/api/apps/kirocrew-flow/dispatch", { repo: l, number: Number(d) }), await s();
      } catch (k) {
        console.error("dispatch failed:", k);
      } finally {
        $(null);
      }
    },
    [e, s]
  ), R = _(
    async (l, d) => {
      const c = window.prompt("Motivo da reprovação no QA:");
      if (c === null) return;
      const k = `${l}#${d}`;
      S(k);
      try {
        await e.post("/api/apps/kirocrew-flow/qa-fail", { repo: l, number: Number(d), reason: c }), await s();
      } catch (D) {
        console.error("qa-fail failed:", D);
      } finally {
        S(null);
      }
    },
    [e, s]
  ), I = _(
    async (l, d) => {
      const c = `${l}#${d}`;
      S(c);
      try {
        await e.post("/api/apps/kirocrew-flow/qa-approve", { repo: l, number: Number(d) }), await s();
      } catch (k) {
        console.error("qa-approve failed:", k);
      } finally {
        S(null);
      }
    },
    [e, s]
  ), T = f ? `Flow - ${a} / ${f.split("/").pop()}` : a, M = i.spec.length + i.ready.length + i.todo.length + i.dev.length + i.review.length + i.review_ok.length + i.qa.length + i.qa_fail.length + i.blocked.length;
  return /* @__PURE__ */ t("div", { style: { padding: "20px 24px", maxWidth: 1400 }, children: [
    /* @__PURE__ */ r(
      Q,
      {
        title: T,
        subtitle: m ? "Carregando…" : h ? `Erro: ${h}` : x ? "⚠️ Modo demo — backend indisponível" : q ? `${M} issues ativas · atualizado ${q.toLocaleTimeString()}` : "",
        actions: /* @__PURE__ */ t("div", { style: { display: "flex", gap: 8 }, children: [
          /* @__PURE__ */ r(b, { size: "sm", variant: "secondary", disabled: !0, children: "Rules" }),
          /* @__PURE__ */ r(b, { size: "sm", variant: "secondary", disabled: !0, children: "Configurações" }),
          /* @__PURE__ */ r(b, { size: "sm", variant: "secondary", onClick: s, disabled: m, children: "↻ Atualizar" })
        ] })
      }
    ),
    /* @__PURE__ */ t("div", { style: { display: "flex", gap: 16, marginTop: 20, flexWrap: "wrap" }, children: [
      /* @__PURE__ */ r(
        A,
        {
          title: "Aguardando SPEC",
          subtitle: "PM especificando",
          issues: i.spec,
          accentColor: "#f59e0b"
        }
      ),
      /* @__PURE__ */ r(
        A,
        {
          title: "Aguardando definição de produto/TL",
          subtitle: "Spec pronta, aguardando priorização",
          issues: i.ready,
          accentColor: "#fbbf24"
        }
      )
    ] }),
    /* @__PURE__ */ r(
      V,
      {
        columns: i,
        onDispatch: K,
        dispatchingKey: C,
        onQaFail: R,
        onQaApprove: I,
        qaBusyKey: E
      }
    ),
    i.blocked.length > 0 && /* @__PURE__ */ t("div", { style: {
      marginTop: 20,
      border: "1px solid #dc262633",
      borderRadius: 10,
      padding: "14px 16px",
      background: "#dc262608"
    }, children: [
      /* @__PURE__ */ t("div", { style: {
        fontWeight: 700,
        fontSize: 13,
        color: "#dc2626",
        marginBottom: 10,
        display: "flex",
        alignItems: "center",
        gap: 8
      }, children: [
        "🔴 Bloqueadas",
        /* @__PURE__ */ r("span", { style: {
          background: "#dc2626",
          color: "#fff",
          borderRadius: 10,
          padding: "1px 7px",
          fontSize: 11
        }, children: i.blocked.length })
      ] }),
      /* @__PURE__ */ r("div", { style: { display: "flex", flexWrap: "wrap", gap: 8 }, children: i.blocked.map((l) => /* @__PURE__ */ r("div", { style: { minWidth: 200, flex: "0 0 auto", maxWidth: 280 }, children: /* @__PURE__ */ r(W, { issue: l }) }, `${l.repo}#${l.number}`)) })
    ] })
  ] });
}
export {
  Z as default
};
