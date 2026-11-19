# **Imagine You Are Running a School 🏫**

Let's understand all 16 database tables using one simple example.

Imagine you are the principal of a school called **Bright Future School**. You want to contact parents of students to invite them to your school's annual function.

Your LeadGen AI Agent works almost exactly like your school management system, but instead of managing students, it manages potential customers and email campaigns.

## **1. First, understand the school**

[Little Students With Their Teacher](https://images.openai.com/static-rsc-4/7NvJ-baUCypmT8m9nPK1ZMJ9_Y11nnELrFULkSrHKVsvzyWurwoGNse-XoJCLyBX-A5hpJFa1LCWjWHRY4NJ9Kwxr0hyH3TTuB4O5GGo3O2OQSrBrd_IcAoWcy5NBJGhW6uLXZPoHfUWQzfS3gqayI_5_aSXNjKk9YJh2KqGUv4bvLNEYz7_I02cHKaHkfGK?purpose=inline)

Your school has:

- One school (Bright Future School).
- Teachers and staff.
- Different classrooms.
- Students.
- Parents and their contact numbers.
- School events.
- Invitations and reminders.
- A record of who attended and who didn't.

Your database stores all this information in separate tables.

## **2. Understand all 16 tables**

### **Group 1: School management**

**1. workspaces — The school itself**

Imagine Bright Future School is using your software. First, you create a record for this school. You save its name, address, timezone and contact information. This is the workspace. If another school joins your software, it gets another workspace.

**2. users — Teachers and school staff**

Your school has a principal, teachers and administrative staff. Each person needs an account to access the software. The users table stores their names, email addresses, password hashes and roles. The principal might have admin access, while a teacher has limited access.

**3. connections — Keys to external services**

Imagine your school wants to send SMS messages using an external messaging company. It needs an account and an API key. The connections table stores these external service credentials securely in encrypted form. In your real LeadGen application, these could be Groq, email providers or lead research services.

### **Group 2: Email infrastructure**

**4. domains — Your school's official identity**

Your school has an official website and email domain, such as `brightfuture.edu`. This table stores your sending domain and checks whether its email authentication records (SPF, DKIM and DMARC) are configured. In your actual project, this helps establish trusted email sending.

**5. mailboxes — Individual school email accounts**

Your school might have `principal@brightfuture.edu` and `admissions@brightfuture.edu`. These are individual email accounts. The mailboxes table stores these accounts, their sending limits and their health status. In your actual project, these accounts send campaign emails.

### **Group 3: School events**

**6. campaigns — A school event**

Imagine your school is organizing an annual function. You create an event called "Annual Function 2026". You save its purpose, target audience, details and status. This is a campaign in your LeadGen application. A campaign represents one organized outreach activity.

**7. sequence_steps — Event invitation and reminders**

You don't want to invite parents just once. You might send an invitation today, a reminder after three days and a final reminder before the event. Each message is a sequence step. This table stores the order and timing of those messages.

### **Group 4: Students and parents**

[A Guide for Non-English-Speaking Parents to communicate](https://images.openai.com/static-rsc-4/nJ3RoqTIlxELPR78qzX8-NK-zXV6Qtw3n9qem9UYfCOzoPKWI3KqoJOW7tpBWhmoEUFnKLeCUox2BXrpV4Pn04oXE4CDtUNgtU5miuKyviwESgf1PiqJ5RaZKZcdn_x4YigYRv4pr23Hclb3FY77XsCBEIqdpeKq7XIrptbfZI4?purpose=inline)

[learningmole.com](https://learningmole.com/effective-communication-non-english-speaking/?utm_source=chatgpt.com)

**8. leads — Students or potential customers**

Imagine your school has 100 students. You store each student's name, class, age and other details in the students register. In your LeadGen application, a lead is equivalent to one student: a person or business you want to contact. The leads table stores their information and qualification score.

**9. lead_emails — Parents' email addresses**

One student might have two parents, and both may have different email addresses. Instead of storing all email addresses inside the student record, you create separate records in lead_emails. Each record connects an email address to its student. This allows one lead to have multiple contact addresses.

### **Group 5: Invitations and communication**

[Parents teacher meeting](https://images.openai.com/static-rsc-4/poVMwky7UUoaKLxEaQZoaPloehlhL2afaX_bP-KHbXOwkbkcMbaLSdqr5sa5eHcfHAFErR7V3XO-sq4zojYPuJ7ljUprD9vf8pYmE9wvwRQ1GJrvPU4YCNnHbV91RZrd63b7_Zvhvsqg9fGbC9lBeI8QIGd4uSKW-rpdXJPbxK1ynnDO3ETGy7rKi3OLC4oG?purpose=inline)

**10. enrollments — Registering students for an event**

Suppose Ahmed is a student at your school. His name is added to the annual function invitation list. Later, he might also be included in the sports day invitation list. Each participation creates a separate enrollment. In your LeadGen application, enrollment connects a lead to a particular campaign and tracks its progress.

**11. messages — Invitations and replies**

Your school sends an invitation to Ahmed's parents. They reply, "Thank you, we will attend." Both the outgoing invitation and incoming reply are stored in the messages table. In your real application, it stores email content, subjects and conversation information.

**12. events — School activity diary**

Imagine a teacher maintains a diary recording that an invitation was sent, a parent replied or a student was registered. The events table does the same thing for your application. It stores important historical activities and status changes, allowing you to investigate what happened.

### **Group 6: Safety and performance**

**13. suppression — Do not contact list**

Imagine Ahmed's parents tell the school, "Please don't send us any more invitations." You put their contact information on a do-not-contact list. Even if another event is organized, they should not receive another invitation. The suppression table performs this job in your LeadGen application.

**14. experiments — Testing two invitation designs**

Imagine you create two invitation designs. Half the parents receive Design A, and the other half receive Design B. You compare which invitation gets more responses. The experiments table stores A/B testing configurations and performance information.

**15. spend_ledger — School expense register**

Your school spends money on printing invitations, SMS messages and other services. You maintain an expense register to track the spending. The spend_ledger table tracks AI usage, email verification costs and lead sourcing expenses in your actual application.

### **Group 7: Software licensing**

**16. license_state — School software subscription**

Imagine your school purchases your software for one year. You give it a license that expires after one year. The license_state table stores the signed license information, expiration date and last validation time. This ensures only authorized clients can use the software.

## **3. Now understand how all these tables work together**

Let's follow Ahmed, a fifth-grade student, from registration to receiving an annual function invitation.

## **Ahmed's journey through the database**

1. **School registration**

   `workspaces` creates Bright Future School.
2. **Teacher login**

   `users` stores Ahmed's teacher and principal accounts.
3. **School communication setup**

   `connections`, `domains` and `mailboxes` configure external services and school email accounts.
4. **Annual function announcement**

   `campaigns` creates the annual function campaign.
5. **Invitation schedule**

   `sequence_steps` defines the invitation and two reminders.
6. **Ahmed's registration**

   `leads` stores Ahmed's information.
7. **Parent contact information**

   `lead_emails` stores his parents' email addresses.
8. **Invitation registration**

   `enrollments` connects Ahmed to the annual function campaign.
9. **Invitation and reply**

   `messages` stores the invitation and his parents' response.
10. **Activity record**

    `events` records every important action.
11. **Do-not-contact protection**

    `suppression` prevents further contact if his parents request it.
12. **Other supporting records**

    `experiments`, `spend_ledger` and `license_state` manage testing, expenses and software authorization.

## **4. What does the database relationship mean?**

Suppose Ahmed is in Class 5 and receives invitations to two events:

- Annual Function
- Sports Day

You should not create Ahmed's student record twice.

Instead:

**leads table**

# **Ahmed**

Student ID: 101

One student, multiple enrollments

**enrollments**

Enrollment 1

Annual Function

**enrollments**

Enrollment 2

Sports Day

This is called a **one-to-many relationship**.

One student (one lead) can have many enrollments.

Similarly:

- One school has many teachers.
- One campaign has many sequence steps.
- One student has many parent email records.
- One enrollment has many messages.

## **5. Finally, what is a database schema?**

Think of a school register.

Every register has:

- A name, such as Students Register.
- Columns, such as Student ID, Name and Class.
- Rows, where individual student information is recorded.
- Relationships with other registers.

A database schema is simply the **blueprint or structure of your database**.

For example:

**leads table**

| **id** | **name** | **company**   |
| ------ | -------- | ------------- |
| 101    | Ahmed    | Bright Future |
| 102    | Ali      | ABC School    |

Illustrative example: the real leads table has more fields.

In PostgreSQL:

- **Table:** A collection of similar records.
- **Column:** A property, such as name or email.
- **Row:** One individual record.
- **Primary key (PK):** A unique ID for each record.
- **Foreign key (FK):** An ID connecting one table to another.
- **Index:** Helps PostgreSQL find records faster.
- **Constraint:** A rule that prevents invalid data.

**The big picture:** Your 16 tables work together like different registers in a school. Each register has its own responsibility, but they are connected through IDs. In your actual LeadGen application, these registers manage businesses, prospects, campaigns, emails, expenses and licensing instead of schools and students.

That's the entire database schema in one school example!