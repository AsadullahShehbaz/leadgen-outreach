import { useEffect, useState } from "react";
import { api, getToken, setToken } from "./api";

const pages = ["Dashboard", "Setup", "Campaigns", "Leads", "Drafts", "Inbox", "Analytics", "Compliance", "System"];

function Status({ error, loading, children }) {
  if (loading) return <p className="muted">Loading...</p>;
  if (error) return <div className="alert error">{error}</div>;
  return children || null;
}

function Login({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [setupStatus, setSetupStatus] = useState(null);
  const [checkingSetup, setCheckingSetup] = useState(true);

  async function loadSetupStatus() {
    setCheckingSetup(true);
    setError("");
    try {
      setSetupStatus(await api("/setup/status"));
    } catch (err) {
      setError(`Could not check setup status: ${err.message}`);
    } finally {
      setCheckingSetup(false);
    }
  }

  useEffect(() => { loadSetupStatus(); }, []);

  async function submit(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const body = new URLSearchParams({ username: email, password });
      const response = await fetch("/api/auth/token", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
      });
      if (!response.ok) throw new Error("Invalid email or password");
      const data = await response.json();
      setToken(data.access_token);
      onLogin();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function createAdmin(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      await api("/setup/admin", {
        method: "POST",
        body: JSON.stringify({
          workspace_name: workspaceName,
          email,
          password,
        }),
      });
      setPassword("");
      setMessage("Admin account created. Sign in with your new credentials.");
      await loadSetupStatus();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  if (checkingSetup) {
    return <main className="login"><p className="muted">Checking setup...</p></main>;
  }

  if (error.startsWith("Could not check setup status:")) {
    return (
      <main className="login">
        <div className="card">
          <h1>LeadGen</h1>
          <div className="alert error">{error}</div>
          <button onClick={loadSetupStatus}>Retry</button>
        </div>
      </main>
    );
  }

  if (!setupStatus?.admin_created) {
    return (
      <main className="login">
        <form className="card" onSubmit={createAdmin}>
          <h1>Set up LeadGen</h1>
          <p>Create the first admin account for this deployment.</p>
          <label>Workspace name<input value={workspaceName} onChange={(e) => setWorkspaceName(e.target.value)} required /></label>
          <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
          <label>Password (12+ characters)<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={12} /></label>
          {error && <div className="alert error">{error}</div>}
          <button disabled={loading}>{loading ? "Creating account..." : "Create admin"}</button>
        </form>
      </main>
    );
  }

  return (
    <main className="login">
      <form className="card" onSubmit={submit}>
        <h1>LeadGen</h1>
        <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        {message && <div className="alert">{message}</div>}
        {error && <div className="alert error">{error}</div>}
        <button disabled={loading}>{loading ? "Signing in..." : "Sign in"}</button>
      </form>
    </main>
  );
}

function SetupPage() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [admin, setAdmin] = useState({ workspace_name: "", email: "", password: "" });
  const [workspace, setWorkspace] = useState({ name: "", sender_identity: "", postal_address: "", timezone: "UTC", accept_responsibility: false });
  const [license, setLicense] = useState("");

  async function load() {
    try {
      setStatus(await api("/setup/status"));
    } catch (err) {
      setError(err.message);
    }
  }
  useEffect(() => { load(); }, []);

  async function createAdmin(event) {
    event.preventDefault();
    setError("");
    try { await api("/setup/admin", { method: "POST", body: JSON.stringify(admin) }); await load(); }
    catch (err) { setError(err.message); }
  }

  async function saveWorkspaceFixed(event) {
    event.preventDefault();
    setError("");
    try { await api("/setup/workspace", { method: "POST", body: JSON.stringify(workspace) }); await load(); }
    catch (err) { setError(err.message); }
  }

  async function storeLicense(event) {
    event.preventDefault();
    setError("");
    try { await api("/setup/license", { method: "POST", body: JSON.stringify({ license_token: license }) }); await load(); }
    catch (err) { setError(err.message); }
  }

  return (
    <div>
      <h1>Setup wizard</h1>
      {error && <div className="alert error">{error}</div>}
      {status && (
        <ul className="checks">
          {Object.entries(status).filter(([key]) => key !== "initialized").map(([key, value]) => (
            <li key={key}><b>{key.replaceAll("_", " ")}</b>: {String(value)}</li>
          ))}
        </ul>
      )}
      {!status?.admin_created && (
        <form className="card" onSubmit={createAdmin}>
          <h2>1. Create admin</h2>
          <label>Workspace name<input value={admin.workspace_name} onChange={(e) => setAdmin({ ...admin, workspace_name: e.target.value })} required /></label>
          <label>Email<input type="email" value={admin.email} onChange={(e) => setAdmin({ ...admin, email: e.target.value })} required /></label>
          <label>Password (12+ characters)<input type="password" value={admin.password} onChange={(e) => setAdmin({ ...admin, password: e.target.value })} required minLength={12} /></label>
          <button>Create admin</button>
        </form>
      )}
      {status?.admin_created && !status.workspace_created && (
        <form className="card" onSubmit={saveWorkspaceFixed}>
          <h2>2. Sender and responsibility</h2>
          <label>Name<input value={workspace.name} onChange={(e) => setWorkspace({ ...workspace, name: e.target.value })} required /></label>
          <label>Sender identity<input value={workspace.sender_identity} onChange={(e) => setWorkspace({ ...workspace, sender_identity: e.target.value })} required /></label>
          <label>Postal address<textarea value={workspace.postal_address} onChange={(e) => setWorkspace({ ...workspace, postal_address: e.target.value })} required /></label>
          <label>Timezone<input value={workspace.timezone} onChange={(e) => setWorkspace({ ...workspace, timezone: e.target.value })} /></label>
          <label><input type="checkbox" checked={workspace.accept_responsibility} onChange={(e) => setWorkspace({ ...workspace, accept_responsibility: e.target.checked })} /> I accept responsibility for my lists and content</label>
          <button>Save workspace</button>
        </form>
      )}
      {status?.admin_created && (
        <form className="card" onSubmit={storeLicense}>
          <h2>3. License</h2>
          <label>License token<input type="password" value={license} onChange={(e) => setLicense(e.target.value)} required /></label>
          <button>Store license</button>
        </form>
      )}
    </div>
  );
}

function DataPage({ title, path, columns }) {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api(path)
      .then((data) => setRows(Array.isArray(data) ? data : [data]))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [path]);
  return (
    <div>
      <h1>{title}</h1>
      <Status loading={loading} error={error}>
        {rows.length === 0 ? <p className="muted">No records yet.</p> : (
          <div className="table-wrap"><table>
            <thead><tr>{columns.map((column) => <th key={column}>{column.replaceAll("_", " ")}</th>)}</tr></thead>
            <tbody>{rows.map((row, index) => <tr key={row.id || index}>{columns.map((column) => <td key={column}>{String(row[column] ?? "")}</td>)}</tr>)}</tbody>
          </table></div>
        )}
      </Status>
    </div>
  );
}

function CampaignsPage() {
  const [campaigns, setCampaigns] = useState([]);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ name: "", product: "{}", icp: "{}", compliance_mode: "standard", require_approval: true });
  async function load() { try { setCampaigns(await api("/campaigns")); } catch (err) { setError(err.message); } }
  useEffect(() => { load(); }, []);
  async function submit(event) {
    event.preventDefault();
    setError("");
    try {
      await api("/campaigns", { method: "POST", body: JSON.stringify({
        name: form.name,
        product: JSON.parse(form.product),
        icp: JSON.parse(form.icp),
        compliance_mode: form.compliance_mode,
        require_approval: form.require_approval,
        sequence_steps: [{ step_no: 1, delay_days: 0, angle_hint: "Opening" }],
      }) });
      await load();
    } catch (err) { setError(err.message); }
  }
  return (
    <div>
      <h1>Campaigns</h1>
      {error && <div className="alert error">{error}</div>}
      <form className="card" onSubmit={submit}>
        <label>Campaign name<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></label>
        <label>Product JSON<textarea value={form.product} onChange={(e) => setForm({ ...form, product: e.target.value })} /></label>
        <label>ICP JSON<textarea value={form.icp} onChange={(e) => setForm({ ...form, icp: e.target.value })} /></label>
        <label>Compliance<select value={form.compliance_mode} onChange={(e) => setForm({ ...form, compliance_mode: e.target.value })}><option value="standard">Standard</option><option value="strict">Strict</option></select></label>
        <label><input type="checkbox" checked={form.require_approval} onChange={(e) => setForm({ ...form, require_approval: e.target.checked })} /> Require draft approval</label>
        <button>Create campaign</button>
      </form>
      {campaigns.map((campaign) => <article className="card" key={campaign.id}><b>{campaign.name}</b><span className="muted"> {campaign.status}</span></article>)}
    </div>
  );
}

function DraftsPage() {
  const [campaigns, setCampaigns] = useState([]);
  const [drafts, setDrafts] = useState([]);
  const [campaignId, setCampaignId] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { api("/campaigns").then(setCampaigns).catch((err) => setError(err.message)); }, []);
  async function loadDrafts(campaignId) {
    setCampaignId(campaignId);
    try { setDrafts(await api(`/campaigns/${campaignId}/drafts`)); } catch (err) { setError(err.message); }
  }
  async function act(campaignId, enrollmentId, action) {
    try { await api(`/campaigns/${campaignId}/drafts/${enrollmentId}/${action}`, { method: "POST" }); await loadDrafts(campaignId); }
    catch (err) { setError(err.message); }
  }
  return (
    <div>
      <h1>Draft approval queue</h1>
      {error && <div className="alert error">{error}</div>}
      <div className="button-row">{campaigns.map((campaign) => <button key={campaign.id} onClick={() => loadDrafts(campaign.id)}>{campaign.name}</button>)}</div>
      {drafts.map((draft) => (
        <article className="card" key={draft.enrollment_id}>
          <h2>{draft.subject || "Untitled draft"}</h2><p>{draft.body}</p>
          <div className="button-row">
            <button onClick={() => act(campaignId, draft.enrollment_id, "approve")}>Approve</button>
            <button onClick={() => act(campaignId, draft.enrollment_id, "reject")}>Reject</button>
          </div>
        </article>
      ))}
    </div>
  );
}

function GenericDataPage({ page }) {
  if (page === "Leads") return <DataPage title="Leads" path="/leads" columns={["person_name", "company_name", "title", "country", "icp_score", "verify_status"]} />;
  if (page === "Inbox") return <DataPage title="Inbox" path="/inbox" columns={["direction", "subject", "sent_at"]} />;
  return null;
}

function AnalyticsPage() {
  const [summary, setSummary] = useState(null);
  const [optimizer, setOptimizer] = useState(null);
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api("/analytics/summary"),
      api("/analytics/optimizer"),
      api("/analytics/report/preview"),
    ])
      .then(([summaryData, optimizerData, reportData]) => {
        setSummary(summaryData);
        setOptimizer(optimizerData);
        setReport(reportData);
      })
      .catch((err) => setError(err.message));
  }, []);

  return (
    <div>
      <h1>Analytics</h1>
      {error && <div className="alert error">{error}</div>}
      {summary && (
        <article className="card">
          <h2>Delivery summary</h2>
          <p><b>{summary.leads}</b> leads</p>
          <p><b>{summary.mailboxes}</b> mailboxes</p>
          <p><b>${Number(summary.spend_today_usd).toFixed(2)}</b> estimated spend today</p>
        </article>
      )}
      {optimizer && (
        <article className="card">
          <h2>Optimizer</h2>
          <p>{optimizer.experiments.length} campaign experiments</p>
          <p>{optimizer.pending_leads_ranked.length} pending leads ranked</p>
          <pre>{JSON.stringify(optimizer.experiments, null, 2)}</pre>
        </article>
      )}
      {report && (
        <article className="card">
          <h2>Weekly report preview</h2>
          <p><b>{report.sent}</b> sent</p>
          <p><b>{report.positive_replies}</b> positive replies</p>
          <p><b>{(report.positive_reply_rate * 100).toFixed(2)}%</b> positive reply rate</p>
          <p>{report.action}</p>
        </article>
      )}
    </div>
  );
}

function CompliancePage() {
  const [email, setEmail] = useState("");
  const [reason, setReason] = useState("manual");
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");
  async function load() { try { setRows(await api("/compliance/suppression")); } catch (err) { setError(err.message); } }
  useEffect(() => { load(); }, []);
  async function submitFixed(event) {
    event.preventDefault();
    try { await api("/compliance/suppression", { method: "POST", body: JSON.stringify({ email, reason }) }); await load(); setEmail(""); }
    catch (err) { setError(err.message); }
  }
  return (
    <div><h1>Compliance</h1>{error && <div className="alert error">{error}</div>}
      <form className="card" onSubmit={submitFixed}>
        <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
        <label>Reason<input value={reason} onChange={(e) => setReason(e.target.value)} required /></label>
        <button>Add suppression</button>
      </form>
      {rows.map((row) => <article className="card" key={row.email_hash}><code>{row.email_hash}</code><p>{row.reason}</p></article>)}
    </div>
  );
}

function SystemPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => { api("/system/status").then(setData).catch((err) => setError(err.message)); }, []);
  return <div><h1>System</h1><Status error={error}>{data && <pre>{JSON.stringify(data, null, 2)}</pre>}</Status></div>;
}

export default function App() {
  const [authenticated, setAuthenticated] = useState(Boolean(getToken()));
  const [page, setPage] = useState("Dashboard");

  async function logout() {
    try { await api("/auth/logout", { method: "POST" }); } catch {}
    setToken(null);
    setAuthenticated(false);
  }

  if (!authenticated) return <Login onLogin={() => setAuthenticated(true)} />;
  return (
    <div className="layout">
      <aside>
        <h2>LeadGen</h2>
        <nav>{pages.map((item) => <button className={page === item ? "active" : ""} key={item} onClick={() => setPage(item)}>{item}</button>)}</nav>
        <button className="logout" onClick={logout}>Log out</button>
      </aside>
      <main>
        {page === "Setup" && <SetupPage />}
        {page === "Campaigns" && <CampaignsPage />}
        {page === "Drafts" && <DraftsPage />}
        {page === "Leads" && <GenericDataPage page="Leads" />}
        {page === "Inbox" && <GenericDataPage page="Inbox" />}
        {page === "Analytics" && <AnalyticsPage />}
        {page === "Compliance" && <CompliancePage />}
        {page === "System" && <SystemPage />}
        {page === "Dashboard" && <DataPage title="Dashboard" path="/system/status" columns={["api", "worker", "version"]} />}
      </main>
    </div>
  );
}
