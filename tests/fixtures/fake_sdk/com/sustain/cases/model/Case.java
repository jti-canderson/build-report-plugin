// A FAKE SDK class for the core suite: build_plan.py resolves traversals against a jar with
// javap, and the core suite must not need a client's real SDK export to prove that. The
// suite compiles this with the JasperReports JDK and jars it into a temp project.
package com.sustain.cases.model;

public class Case extends DomainBase {
    private String caseNumber;
    private String caseType;
    private Case parent;               // self-reference: lets a test walk past the depth limit
    private java.util.List<Party> parties;
    public String getCaseTypeLabel() { return caseType; }
}
