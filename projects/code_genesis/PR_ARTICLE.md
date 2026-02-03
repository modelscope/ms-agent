# Code Genesis: A Production-Ready Multi-Agent Framework for End-to-End Project Generation

We introduce **Code Genesis**, an open-source, compositional code agent framework that orchestrates specialized AI agents to autonomously generate production-ready software projects from natural language requirements. Code Genesis implements a holistic engineering pipeline that spans from requirement analysis to deployment-ready artifacts, achieving high-fidelity project generation with minimal human intervention.

## 1. Design Philosophy & Architecture

### 1.1 Core Principles

Code Genesis is built on three foundational pillars:

**Compositional Workflow Architecture**: We adopt a modular agent design where each specialized agent encapsulates a distinct phase of the software development lifecycle. This compositional approach enables:
- **Declarative workflow orchestration** through YAML-based configuration
- **Pluggable agent replacement** for domain-specific customization
- **Transparent execution tracing** for debugging and optimization

**Topology-Aware Code Generation**: Code Genesis introduces a **dependency-aware topological scheduler** that:
- Constructs a directed acyclic graph (DAG) of file dependencies
- Enables **parallel code generation** for independent modules while respecting dependency constraints
- Guarantees that generated code references pre-existing entities, eliminating hallucinated imports

**Production-First Engineering**: We prioritize deliverable quality over prototyping speed by integrating:
- **Language Server Protocol (LSP) validation** at code generation time
- **Protocol-driven API contracts** to ensure frontend-backend consistency
- **Automated dependency resolution** and environment bootstrapping
- **Runtime verification and self-healing** through iterative refinement

### 1.2 Workflow Orchestration

Code Genesis provides **two configurable workflow modes** to balance between generation quality and execution speed, enabling users to select the optimal strategy based on project complexity:

#### Standard Workflow (Production-Grade)
<img alt="Simple Workflow Diagram" src="asset/workflow_code_genesis.png" />

The standard pipeline implements a rigorous 7-stage process optimized for complex, production-ready projects:

```
User Story → Architect → File Design → File Order → Install → Coding → Refine
```

**Pipeline Stages** (Refer to Section 2 for more details):
1. **User Story Agent**: Requirement parsing and augmentation
2. **Architect Agent**: Technology stack selection and module decomposition
3. **File Design Agent**: Physical file structure generation
4. **File Order Agent**: Dependency graph construction and topological sorting
5. **Install Agent**: Environment bootstrapping and dependency resolution
6. **Coding Agent**: Topology-aware code synthesis with LSP validation
7. **Refine Agent**: Runtime verification and automated deployment

This workflow guarantees architectural coherence, eliminates reference errors through explicit dependency modeling, and produces enterprise-grade codebases with comprehensive documentation.

#### Simple Workflow (Rapid Prototyping)
<img alt="Simple Workflow Diagram" src="asset/simple_workflow_code_genesis.png" />

For lightweight projects or quick iterations, the simple workflow condenses the pipeline into 4 core stages:

```
Orchestrator → Install → Coding → Refine
```

**Streamlined Process**:
1. **Orchestrator Agent**: Unified requirement analysis, architecture design, and file planning in a single reasoning step
2. **Install Agent**: Dependency resolution and environment setup
3. **Coding Agent**: Direct code generation with integrated file ordering
4. **Refine Agent**: Validation and deployment

The orchestrator agent encapsulates the first four stages of the standard workflow, sacrificing granular traceability for faster time-to-prototype. This mode is ideal for proof-of-concept projects, educational demos, or single-feature applications.

#### Workflow Comparison

| Aspect                    | Standard Workflow          | Simple Workflow           |
|---------------------------|----------------------------|---------------------------|
| **Agent Stages**          | 7 specialized agents       | 4 consolidated agents     |
| **Architecture Quality**  | Explicit, auditable design | Implicit, monolithic design |
| **Generation Time**       | Moderate (thorough planning) | Fast (direct execution) |
| **Use Cases**             | Production systems, complex apps | Prototypes, demos, simple tools |

---

## 2. Multi-Agent System Design

Code Genesis decomposes project generation into seven specialized agents, each operating on structured intermediate representations to maintain engineering rigor throughout the pipeline.

### 2.1 User Story Agent: Semantic Requirement Engineering

**Objective**: Transform informal user requirements into structured, engineering-grade user stories.

**Methodology**:
- **Semantic Parsing**: Employs natural language understanding to extract functional requirements, quality attributes, and implicit constraints
- **Requirement Augmentation**: Proactively identifies missing specifications (e.g., authentication, error handling, accessibility) based on project type
- **Standardization**: Outputs INVEST-compliant user stories

### 2.2 Architect Agent: System Blueprint Synthesis

**Objective**: Generate a cohesive system architecture with technology stack selection and module decomposition.

**Design Outputs**:
- **Technology Stack (Framework)**: Frontend/backend frameworks, databases, middleware with version specifications
- **Communication Protocol**: RESTful API, GraphQL, or WebSocket with schema definitions
- **Module Hierarchy**: Logical partitioning with explicit inter-module dependencies

### 2.3 File Design Agent: Physical Project Structure

**Objective**: Materialize the architectural blueprint into a concrete file tree with package structures.

**Capabilities**:
- **Layer-Based Organization**: Implements horizontal slicing (services, controllers, repositories, models), grouping same-level components across modules into unified packages
- **Module-to-File Mapping**: Reads the module list from `modules.txt` and designs a complete file list for each module with descriptions

### 2.4 File Order Agent: Dependency-Driven Scheduling

**Objective**: Establish a topologically sorted generation sequence to prevent reference errors.

**Methodology**:
1. **Dependency Analysis**: Analyzes file design and framework specifications to infer dependency relationships between files (e.g., DAO ← Service ← Controller, CSS ← JS ← HTML)
2. **Index-Based Grouping**: Assigns each file an index number where:
   - Files with the same index are functionally independent and can be generated in parallel
   - Files with higher indices can depend on files with lower indices, but not vice versa
3. **Completeness Validation**: Ensures all files from file_design are included in the ordering with runtime assertions

### 2.5 Install Agent: Environment Bootstrapping

**Objective**: Prepare the runtime environment with all necessary dependencies.

**Workflow**:
1. **Dependency Manifest Generation**: Synthesizes complete dependency lists from file design and technology stack
2. **Package Manager Invocation**: Executes `pip install`, `npm install`, `mvn install` within the workspace
3. **Environment Validation**: Verifies installation success and resolves version conflicts

### 2.6 Coding Agent: Topology-Aware Implementation

**Objective**: Generate high-quality, production-ready source code adhering to the established architecture and file order.

**Engineering Rigor**:
- **Topological Awareness**: Strictly follows the dependency-sorted file order to guarantee reference validity
- **Protocol Compliance**: Implements API contracts exactly as specified in the architectural protocol
- **Relative Path Imports**: Uses workspace-relative imports for portability across environments

**LSP Integration**: Each generated file is validated through Language Server Protocol checks:
- **Syntax Validation**: Ensures syntactic correctness
- **Type Checking**: Verifies type consistency (for statically typed languages)
- **Import Resolution**: Confirms all imports resolve to existing files

**Self-Correction Loop**: If LSP reports errors, the agent performs localized revisions without regenerating the entire file, maintaining coherence while fixing specific issues.

### 2.7 Refine Agent: Runtime Validation & Deployment

**Objective**: Serve as the final quality gate through dynamic execution and automated repair.

**Refinement Process**:
1. **Compilation/Execution Testing**: Attempts to run the generated project (e.g., `python app.py`, `npm start`)
2. **Error Pattern Recognition**: Detects common multi-agent hallucinations:
   - Framework version mismatches
   - API signature inconsistencies
   - Protocol violations (e.g., incorrect HTTP methods)
   - Third-party library API misuse
3. **Surgical Corrections**: Applies minimal, targeted fixes to resolve runtime errors
4. **Integration Testing**: Validates frontend-backend communication, database connectivity, and middleware functionality

**Automated Deployment**: Upon successful validation, the agent leverages EdgeOne Pages (via MCP integration) to:
- Packages the project (excluding build artifacts and dependencies) into a deployment-ready archive
- Deploys to EdgeOne Pages cloud platform automatically
- Provides publicly accessible URLs for immediate user interaction and testing

---

## 3. Empirical Evaluation

To benchmark Code Genesis's end-to-end project generation capabilities, we conducted a comprehensive comparative study against state-of-the-art code agents.

### 3.1 Task Corpus

We curated a benchmark of **30 real-world project specifications** spanning productivity tools, utilities, dashboards, and API-driven applications (Table 1):
- **20 Simple Projects** (10-20 files): Single-page applications including calculators, timers, converters, and basic CRUD tools
- **10 Medium Projects** (20 files): Multi-page applications with databases, real-time features (WebSocket chat), external API integration, and interactive UI components

| ID | Category | Project Name | Description |
|----|----------|--------------|-------------|
| 1  | Simple   | Personal Portfolio Website | A static site to display skills, projects, and contact info |
| 2  | Simple   | To-Do List Application | A basic CRUD app to add, edit, delete, and mark tasks as done |
| 3  | Simple   | Random Quote Generator | An app that fetches and displays random quotes from a local array or API |
| 4  | Simple   | Digital Clock & Timer | A web app displaying current time with stopwatch and countdown features |
| 5  | Simple   | Simple Calculator | A web-based calculator performing basic arithmetic operations |
| 6  | Simple   | Unit Converter | An app to convert between metric and imperial units (length, weight, temp) |
| 7  | Simple   | Color Palette Generator | A tool to generate random color schemes and copy hex codes |
| 8  | Simple   | Markdown Previewer | An editor that renders Markdown text into HTML in real-time |
| 9  | Simple   | Tip Calculator | A utility to calculate tips per person based on bill amount |
| 10 | Simple   | Age Calculator | An app that calculates exact age in years, months, and days from a birthdate |
| 11 | Simple   | Lorem Ipsum Generator | A tool to generate placeholder text of specified length |
| 12 | Simple   | Password Generator | An app to generate secure random passwords with customizable criteria |
| 13 | Simple   | BMI Calculator | A health tool to calculate Body Mass Index from height and weight |
| 14 | Simple   | Currency Converter | A converter using fixed exchange rates to swap between currencies |
| 15 | Simple   | Digital Business Card | A responsive card layout displaying user contact details |
| 16 | Simple   | Simple Image Gallery | A grid of images with a lightbox modal for viewing |
| 17 | Simple   | Pomodoro Timer | A productivity timer with work/break intervals |
| 18 | Simple   | Expense Tracker (Basic) | A list to log daily expenses and show a total sum |
| 19 | Simple   | Contact List Address Book | A CRUD app to manage names, numbers, and emails |
| 20 | Simple   | Weather Widget | A component displaying weather for a hardcoded location (mock data) |
| 21 | Medium   | Blog Application | A CMS to create, read, update, and delete blog posts with a database |
| 22 | Medium   | Real-time Chat App | A chat room using WebSockets for instant messaging between users |
| 23 | Medium   | Weather Dashboard | An app fetching real-time weather data from an external API for searched cities |
| 24 | Medium   | Movie Search App | An interface to search and view movie details using the OMDB/TMDB API |
| 25 | Medium   | Kanban Task Board | A Trello-like board with drag-and-drop tasks across columns |
| 26 | Medium   | E-commerce Product Page | A dynamic product page with image gallery, options, and add-to-cart logic |
| 27 | Medium   | Expense Tracker with Charts | A finance app with visual charts (Pie/Bar) for spending categories |
| 28 | Medium   | Music Player | A web audio player with play, pause, skip, and playlist functionality |
| 29 | Medium   | GitHub User Search | An app using GitHub API to show user profiles and repositories |
| 30 | Medium   | Image Compressor | A tool to upload images and download compressed versions |

*Table 1: Task corpus spanning productivity tools, utilities, data visualization, and API-driven applications*

### 3.2 Baseline Code Agents & Foundation Models

**Code Agent Frameworks**:
- **Copilot** (closed-source)
- **TRAE CN** (closed-source)
- **OpenCode** (open-source)

**Foundation Models**:
- **Qwen3-Coder-Plus** for simple projects
- **Qwen3-Max** for medium projects

### 3.3 Evaluation Metrics

We assess generated projects across three dimensions:

1. **One-Time Completion (Compile)**: Proportion of projects that compile/run successfully without manual intervention after a single generation pass

2. **Function Availability**: Proportion of projects meeting all specified functional requirements without critical bugs (scored by independent reviewers on requirement checklists)

3. **Aesthetic Appeal**: User interface quality assessment based on color scheme coherence, layout professionalism, and responsiveness
### 3.4 Results & Analysis

| Code Agent   | One-Time Completion | Function Availability | Aesthetic Appeal |
|--------------|----------------------------|------------------------------|-------------------------|
| **Code Genesis** | 28 (93.3%)          | 27 (90.0%)               | **11** (36.7%)          |
| Copilot      | 28 (93.3%)                 | 25 (83.3%)                   | 4 (13.3%)               |
| TRAE CN      | **29** (96.7%)             | **28** (93.3%)               | 9 (30.0%)               |
| OpenCode     | 28 (93.3%)                 | 25 (83.3%)                   | 6 (20.0%)               |

*Table 2: Comparative performance across evaluation dimensions*

**Key Findings**:

1. **Compilation Success**: Code Genesis achieves competitive compilation rates (93.3%), matching proprietary solutions. The topological file ordering and LSP validation contribute to high first-pass success rates.

2. **Functional Completeness**: Code Genesis demonstrates superior functional availability (90.0%) compared to Copilot and OpenCode, attributed to the User Story Agent's requirement augmentation and the Refine Agent's runtime validation loop.

3. **Aesthetic Quality**: Code Genesis significantly outperforms all baselines in UI aesthetics (36.7% vs. 13.3%-30.0%). This advantage stems from:
   - **Design-Aware Prompting**: The Architect Agent incorporates UI/UX best practices into framework selection
   - **Component Library Integration**: Preferential use of modern design systems (Tailwind CSS, Material-UI, Ant Design)
   - **Refinement Feedback**: The Refine Agent applies visual regression testing and layout validation

---

## 4. Contributions & Impact

Code Genesis advances the state-of-the-art in automated software engineering through:

1. **Open-Source Production-Grade Agent Framework**: The fully transparent, customizable multi-agent system for end-to-end project generation

2. **Topology-Aware Code Synthesis**: Novel application of dependency-driven scheduling to eliminate hallucinated references and enable parallel generation

3. **LSP-Integrated Validation**: Real-time language server feedback during code generation

4. **Holistic Engineering Pipeline**: Unified workflow spanning requirement analysis, architecture design, implementation, and deployment—delivering immediately usable software artifacts

5. **Empirical Benchmark**: Comprehensive evaluation framework for assessing full-project generation capabilities

---

## 5. Future Directions

- **Incremental Code Evolution**: Extending Code Genesis to handle feature additions and refactoring of existing codebases
- **Multi-Modal Specification**: Supporting design mockups and database schemas as input modalities

---

## Acknowledgments

We thank the open-source community for their invaluable feedback and the ModelScope team for infrastructure support. Special recognition to the developers of foundation models (Qwen series) that power Code Genesis's generation capabilities.

---
