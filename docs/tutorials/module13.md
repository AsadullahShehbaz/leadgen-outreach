# **Module 13: Build a React Dashboard and Setup Wizard**

This tutorial explains how to build the frontend dashboard for your LeadGen application using **React, Vite, FastAPI, and Caddy**.

We'll understand what each component does, how the frontend communicates with the backend, and how users operate the complete application.

## **1. What are we building?**

Until now, most of our LeadGen functionality has been implemented in the backend.

But imagine giving this application to a client. They shouldn't need to:

- Call API endpoints manually.
- Write SQL queries to view leads.
- Use terminal commands to approve email drafts.
- Check logs to understand campaign performance.

They need a proper dashboard where they can manage everything.

That's what Module 13 builds.

[Email Marketing SaaS Dashboard UIUX by ilias miah ✪ Hire Now on Dribbble](https://images.openai.com/static-rsc-4/vwI21uUocT0hzNw9FT0iD6FYPxhpaT1ArVJktwoEpxhR-h_HcWDySagU7uMp8Sj51yN8VoM3_kwt3K_wfcJNNYUrfUIRiV9LJrRjsaEfWRntNROUfnEgcI6LcRzs7A3HPY3gdr43QthzDVfrfwGo2lwBu0lm3YUDMgJsKl8tpOI?purpose=inline)

[dribbble.com](https://dribbble.com/shots/27244132-Email-Marketing-SaaS-Dashboard-UIUX?utm_source=chatgpt.com)

Our application will have two major parts:

**Frontend — React + Vite**

What the user sees and interacts with: forms, tables, buttons, dashboards, and reports.

HTTP API requests and responses

**Backend — FastAPI**

Authentication, business logic, database operations, compliance checks, and background-job scheduling.

The important principle is:

**React displays information and collects user actions. FastAPI remains responsible for making decisions and changing application data.**

## **2. Understand the complete architecture**

Let's imagine a client opens:

`https://leadgen.example.com`

The request reaches Caddy, which serves the React application. When React needs data, it calls the FastAPI backend through the same domain.

[BootcampCode 3.02: React Setup | by PrimerPy | Jan, 2026 | Medium](https://images.openai.com/static-rsc-4/cOUIhR5tElQdSKoyazuui2O8dJzXC_OYVuSf9pdou3gwBCxYBsYBVcOvFYtQlWK5Tjgm-0cs9vWD3CpEh05IHFb6oO3j6OrGX139qkjpvY3XxCeoc4xlRn2kct1fhgymXnSZWIXYopSR20QoDsAPHlrQkLJKAUFEo9W5siuq33s?purpose=inline)

[primerpy.medium.com](https://primerpy.medium.com/bootcampcode-3-02-react-setup-80179b60c68e?utm_source=chatgpt.com)

The architecture works like this:

| Component  | Responsibility                                   |
| ---------- | ------------------------------------------------ |
| React      | Dashboard UI                                     |
| Vite       | Frontend development server and production build |
| Caddy      | HTTPS, static file serving, API routing          |
| FastAPI    | Backend API and business logic                   |
| PostgreSQL | Persistent application data                      |
| Redis      | Temporary data and background-job queue          |
| ARQ        | Background job execution                         |

### **How does React communicate with FastAPI?**

For example, when a user opens the campaigns page:

```
1. User opens /campaigns
2. React loads the campaigns page
3. React sends GET /api/campaigns
4. Caddy forwards it to FastAPI as GET /campaigns
5. FastAPI retrieves campaigns from PostgreSQL
6. FastAPI returns JSON
7. React displays campaigns in a table
```

Notice that the browser only communicates with the public application domain. It doesn't need to know internal Docker addresses.

## **3. Build the backend API surfaces**

Before building the dashboard, we need APIs that provide the information and actions required by each screen.

For example, imagine the frontend needs to display all campaigns.

We create:

```
GET /campaigns
```

FastAPI returns JSON:

```
[
  {
    "id": "campaign-123",
    "name": "SaaS Outreach",
    "status": "draft",
    "enrollment_count": 120
  }
]
```

React receives this response and displays it.

### **Why do we need Pydantic schemas?**

Never return complete database models directly without controlling their fields.

Suppose your campaign model contains:

```
class Campaign:    id: str    name: str    status: str    vendor_api_key: str    smtp_password: str
```

The dashboard doesn't need vendor API keys or SMTP passwords.

Create a dedicated response schema:

```
from pydantic import BaseModelclass CampaignResponse(BaseModel):    id: str    name: str    status: str    enrollment_count: int
```

Now FastAPI returns only the fields needed by the frontend.

**Remember:** Pydantic response schemas help control what data leaves your backend.

### **Important backend rule: Workspace isolation**

Your application has dedicated deployments, but users can still belong to different workspaces.

Every dashboard endpoint must:

1. Authenticate the user using `get_current_user`.
2. Obtain their `workspace_id`.
3. Retrieve only objects belonging to that workspace.
4. Verify ownership before updating or deleting an object.

Example:

```
@router.get("/campaigns")async def get_campaigns(    user=Depends(get_current_user),    session=Depends(get_session),):    return await session.execute(        select(Campaign).where(            Campaign.workspace_id == user.workspace_id        )    )
```

This is an illustrative example; adapt the query and result serialization to your existing database implementation.

## **4. Implement the setup wizard**

A new client should not need technical knowledge to configure LeadGen.

Instead of asking them to configure everything through API requests, we provide a guided setup wizard.

[Multi Step Form UI/UX Design by Thisara Neelawala on Dribbble](https://images.openai.com/static-rsc-4/kJPGQWs-fx1Ocic1HTVoT4g3klGA0mqYrfcmYjLkwWw9UKKAgEeihrt64iWcXZ3X9pTGZTtCuFTUmS3c7D333e-1INbP4Oi-QzPUqhrqK6aeSlVfMOvMDFstp-IFp2dWdNJcNcDb4SY49tRhCliSTu1COY2IP3T6P6AKkOR6fng?purpose=inline)

[dribbble.com](https://dribbble.com/shots/27745631-Multi-Step-Form-UI-UX-Design?utm_source=chatgpt.com)

The wizard contains eight steps:

1. **Create admin and workspace**

   Create the first administrator account and workspace.
2. **Configure license**

   Submit the license and verify its existing signed-license status.
3. **Configure connections**

   Add the required LLM and verifier provider credentials.
4. **Configure sender identity**

   Add sender name, postal address, timezone, and responsibility acceptance.
5. **Configure sending domain**

   Display SPF, DKIM, and DMARC DNS instructions.
6. **Configure mailbox**

   Add SMTP/IMAP credentials and inspect mailbox health and warming status.
7. **Configure limits**

   Set sending limits and paid-work spending caps.
8. **Complete setup**

   Display readiness and guide the user to create their first campaign.

### **How does the wizard know which step to display?**

Use:

```
GET /setup/status
```

Example response:

```
{
  "completed": false,
  "steps": {
    "admin": true,
    "license": true,
    "connections": true,
    "sender": false,
    "domain": false,
    "mailbox": false
  }
}
```

React reads this response and determines which step is incomplete.

**Important security rule:** When a user submits a provider password or API key, send it to FastAPI over HTTPS. Do not store it in browser storage or keep it in frontend state after successful submission.

## **5. Implement authentication and authorization**

Your dashboard must be accessible only to authenticated users.

The existing application already uses OAuth2 password authentication and JWT.

The frontend login flow is:

```
User enters email and password
             |
             v
React calls /auth/login
             |
             v
FastAPI validates credentials
             |
             v
FastAPI returns JWT
             |
             v
React keeps token in memory
             |
             v
React sends token with API requests
```

Example API request:

```
const response = await fetch("/api/campaigns", {
  headers: {
    Authorization: `Bearer ${accessToken}`,
  },
});
```

For logout:

```
await fetch("/api/auth/logout", {
  method: "POST",
  headers: {
    Authorization: `Bearer ${accessToken}`,
  },
});
```

Your actual Caddy prefix configuration determines how `/api/auth/logout` reaches the existing `/auth/logout` endpoint.

The backend must revoke the JWT using the existing Redis-backed logout functionality.

**Interview point:** Authentication determines who the user is. Authorization determines what that user is allowed to access.

## **6. Build the dashboard pages**

Now we can build the actual React application.

The dashboard has nine main areas.

[CRM Dashboard Template Built with Bootstrap 5 & React | CRMS](https://images.openai.com/static-rsc-4/7VTD9aOqPbUIfme7bdO6-6TptF_UE5RBjEjointOD4rApyVu1-Nigev_Z8gpfSGSOsv5bj7iTHY23VZQxe_l0qv1befAZKGfFlsniEfRU-ipZ2w97IisYD3hUIC8gejyxDkLkUfRKj2G09W7qzrLZ_O5UIsoQH-gVHS42MgLS9U?purpose=inline)

**1. Dashboard**

Displays campaign health, queue status, replies, bounce alerts, spending, and backup status.

[15 Apps That Will Help You Write Better Prospecting Emails](https://images.openai.com/static-rsc-4/wdKBTPRn8iMyzLp9T16esZyqd6x8ZScT9rcbmvfVgkj8EUza_-tc4sJG2YbVTbcIQplTCU1tWMRDDtTBHu633cuw-gY7BYHiydR1I8rwYCXFQE3CXo_6yYBofdULPxs_rX-XVZtULemiXEq7vICWFnr1M8SysghKldx9NvqCNTo?purpose=inline)

**2. Campaigns**

Create campaigns, define products, specify the ideal customer profile (ICP), and configure email sequences.

[Sprzedaż i produkcja w jednym systemie - monday CRM dla produkcji | Deviniti](https://images.openai.com/static-rsc-4/R9pBB5RxHv56U208rzYM5j9t-ObJJF29lSpRltHmmGIDg3leaq4rx1So6eSYOvxu1DO717nFhom30sbHcdwveUprPid26E5TeG05TiicA0gjAHwG6GUC-DLRn7tKo7WCLJzhXh9RUVfCFFjVHR0RYk4gEAqOPpH9I_RsHLT7UgM?purpose=inline)

**3. Leads**

Import CSV files, view leads, inspect verification status, and perform forget-person actions.

[\[Integration\] Human in the Loop Review for Generative AI Automations | Zapier Community](https://images.openai.com/static-rsc-4/d182_MtQ3sy1tmRqFmdtjP_lXitdYvLFJwJuPaIggMRD1PBihDPMEHk6d2ZrU0DsaukgCOir-jAILY2sgkkTP7BwUWdcrXjX6khiI8-aOYq97a5yKGFbK3DshG46pV4wYEkVWjLpzMQAyAPE-9AK3eivPM6cXepqgSkZCp9qj0A?purpose=inline)

**4. Draft approval**

Review AI-generated email drafts and approve or reject them.

[Close Tickets Faster with Free Shared Inbox Software | HubSpot](https://images.openai.com/static-rsc-4/2lhhfx-6aaMoJACx6VduzJjX6qFRhdbLCqXAUtlPYHafdlmtRwYWhdOyQ9P1GptQKFL4Sn5FOX1e_ucER5DbS36Nu6HWoxoDwWoSOaCo5Tx7lwGvCBdI3zPfKs6EHn1KzcfWeIdxWB6v8IpDfDeFeGRFL5J2_XSSh5fJp6ZtW6Q?purpose=inline)

**5. Inbox**

View incoming messages, linked leads, campaigns, and reply classifications.

[E-Mail Marketing Campaigns Dashboard](https://images.openai.com/static-rsc-4/LEadBODknkThye5Dc4XgvelifmZjGV-GbdVvqdO9pTrd1qJdxH2BbbqYMu_CRhfHg6Z07IpTvBLCd-EyLSrLi16t8gxOGMdAcmmccpTmPGfJgKzLeEyl-OsaNq80Cx689het1WEgA3tlgSiRd7lEYy3R0zPmiD0b0pFRuPmIllI?purpose=inline)

**6. Analytics**

View sourced leads, verified leads, campaign outcomes, replies, and estimated spending.

**7. Compliance**

Manage suppression lists, sender identity, postal address, and compliance settings.

[System Health Dashboard by Quadiz on Dribbble](https://images.openai.com/static-rsc-4/iLDOYsv6xPCae-kGls-sWj2o-9nAK5F2dpHDiUr0YitVH4RjwvdcPChq8BW6zjrBdaPOLCxQI2wBVWEuYfpMyciozBLKkI-NbyfljYc4wM2DMgoDHj3Dv4kHuerWc-tGgC1Tp67TRuV9_rnF3SHNNNKZdAujIhmyLCKy5BoqfCg?purpose=inline)

**8. System**

Display application version, health, license, backup status, and update availability.

The ninth area is **Login and Setup Wizard**, which handles first-time access and configuration.

### **Important: What each screen must not do**

The dashboard is not a replacement for your backend services.

For example:

- Approving a draft must call the existing state machine.
- Forgetting a person must call the existing compliance service.
- Verifying a lead must use the existing verifier pipeline and spend cap.
- Importing leads must use the existing source pipeline.
- Inbox must not send replies.
- Analytics must not introduce open tracking.

React should never independently implement these business rules.

## **7. Understand draft approval using a real example**

Suppose your AI system generates an email for a potential customer.

The enrollment currently has this status:

```
drafted
```

The user opens the Draft Approval page and sees:

```
Subject: Improve your customer support workflow

Body: Hello John, ...

[Approve] [Reject]
```

When the user clicks Approve:

```
React
  |
  | POST /campaigns/{id}/drafts/{enrollment_id}/approve
  v
FastAPI
  |
  | Verify user and workspace ownership
  | Verify enrollment is in drafted state
  v
Existing State Machine
  |
  | transition(..., "queued", ...)
  v
Enrollment status = queued
```

The important part is that React does not directly update the database.

FastAPI calls:

```
await state_machine.transition(    enrollment,    "queued",    reason="human_approved",)
```

This preserves your existing state-transition rules.

The approval endpoint must also prevent duplicate approval from creating duplicate enqueue operations.

## **8. Build a shared React API client**

Instead of writing `fetch()` separately in every page, create one reusable API client.

Project structure:

```
frontend/
├── package.json
├── vite.config.js
├── index.html
├── src/
│   ├── main.jsx
│   ├── App.jsx
│   ├── api/
│   │   └── client.js
│   ├── components/
│   │   ├── Layout.jsx
│   │   ├── Loading.jsx
│   │   ├── ErrorState.jsx
│   │   └── EmptyState.jsx
│   └── pages/
│       ├── Login.jsx
│       ├── SetupWizard.jsx
│       ├── Dashboard.jsx
│       ├── Campaigns.jsx
│       ├── Leads.jsx
│       ├── DraftQueue.jsx
│       ├── Inbox.jsx
│       ├── Analytics.jsx
│       ├── Compliance.jsx
│       └── System.jsx
└── tests/
```

Example API client:

```

const API_BASE = "/api";

export async function apiRequest(
  path,
  { token, method = "GET", body } = {}
) {
  const headers = {};

  // Attach JWT when the user is authenticated.
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  // Send JSON only when a body exists.
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined
      ? undefined
      : JSON.stringify(body),
  });

  // Never pretend a failed API request succeeded.
  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

```

Now any page can reuse it:

```
const campaigns = await apiRequest("/campaigns", {
  token: accessToken,
});
```

This makes authentication, request handling, and error handling easier to maintain.

## **9. Integrate React with Caddy and Docker**

After development, Vite builds your React application into static files.

Run:

```
npm run build
```

The output is:

```
frontend/dist/
├── index.html
└── assets/
    ├── index-abc123.js
    └── index-def456.css
```

Caddy serves these files to users.

Your Caddy configuration should handle two types of requests:

```
leadgen.example.com {
    # Remove /api prefix before forwarding to FastAPI.
    handle_path /api/* {
        reverse_proxy api:8000
    }

    # Serve React application.
    handle {
        root * /srv/frontend
        try_files {path} /index.html
        file_server
    }
}
```

Here, `handle_path` strips `/api` automatically.

For example:

```
Browser request:
GET /api/campaigns

Caddy forwards:
GET /campaigns

FastAPI endpoint:
GET /campaigns
```

The `try_files` directive is important because React uses client-side routing. If a user refreshes `/campaigns`, Caddy must return `index.html` rather than a 404.

Your Docker setup should mount or copy the built frontend into the directory Caddy serves.

**Security:** Never copy `.env`, `node_modules`, development files, or frontend secrets into the public static directory.

## **10. Testing: How do we know everything works?**

We need both backend and frontend tests.

### **Backend tests**

Use pytest with fake database sessions and fake providers.

Examples:

| Test                                       | Expected result                                    |
| ------------------------------------------ | -------------------------------------------------- |
| Unauthenticated campaign request           | 401/403                                            |
| User accesses another workspace's campaign | Access denied                                      |
| Campaign response contains SMTP password   | Test fails                                         |
| Approve drafted enrollment                 | Changes to queued once                             |
| Approve already queued enrollment          | Rejected or safely handled                         |
| Forget person                              | Suppression happens before personal-field deletion |
| Invalid campaign compliance mode           | Validation error                                   |

### **Frontend tests**

Use fake API responses rather than real backend services.

Examples:

- Login redirects to the correct page.
- Setup wizard displays incomplete steps.
- Campaign creation displays validation errors.
- Lead import displays success or failure.
- Draft approval updates the visible status.
- Inbox doesn't show a send-reply action.
- API errors are clearly displayed.

### **Manual acceptance walkthrough**

Finally, manually perform the complete user journey:

**Module 13 acceptance test**

0 of 14 completed

0%

Create the first admin and workspace

Configure and verify the license

Configure provider connections

Set sender identity and responsibility acceptance

Configure domain and mailbox

Set spending and sending limits

Log in to the dashboard

Create a campaign and sequence

Import and review leads

Review and approve an email draft

Open the inbox and inspect a reply

Review analytics and spending

Manage suppression and compliance settings

Inspect system health and backup status

Reset checklist

Only mark the module implemented when the complete walkthrough works and the required tests pass.

## **11. Important concepts to remember for interviews**

| Concept                    | Simple explanation                                      |
| -------------------------- | ------------------------------------------------------- |
| React                      | JavaScript library for building user interfaces         |
| Vite                       | Frontend development and build tool                     |
| API client                 | Reusable code for communicating with backend APIs       |
| JWT                        | Token used to authenticate API requests                 |
| Pydantic DTO               | Defines the data returned by an API                     |
| Reverse proxy              | Receives requests and forwards them to backend services |
| SPA fallback               | Returns React's `index.html` for frontend routes        |
| Workspace isolation        | Prevents users from accessing other workspaces' data    |
| Loading/error/empty states | Different UI states while fetching or displaying data   |

## **12. What is outside Module 13?**

Keep these boundaries clear:

- **Module 13:** Dashboard, setup wizard, frontend API integration, and user interactions.
- **Module 14:** Thompson sampling, ICP optimization, and weekly performance reports.
- **Modules 5–6:** Email sending, receiving, bounce handling, and reply classification.
- **Module 9:** Existing lead-source and import pipelines.
- **Module 12:** Docker packaging and production deployment.

Module 13 connects the existing backend capabilities into one usable product. It should not duplicate their business logic.

## **Final mental model**

Think of LeadGen as a school:

- React is the school's reception and notice boards where students interact.
- FastAPI is the administration office that processes requests.
- PostgreSQL is the permanent student-record register.
- Redis is the temporary task board.
- ARQ workers are staff members completing background tasks.
- Caddy is the main gate directing visitors to the right place.

**The biggest engineering lesson of Module 13: Build a frontend that makes your backend easy to use without bypassing the backend's security, compliance, and business rules.**