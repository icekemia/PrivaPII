# First-use walkthrough

Use this fictional case to test PrivaPII locally. The examples work in **Rules only** mode. Use a new workspace so the expected result is easy to check.

## Prepare the two documents

Copy each block into a separate UTF-8 text file, named `application.txt` and `reply.txt`.

**Application**

```text
Dokumentas išduotas 2026 m. lapkričio 16 d.
1. Pareiškėja Eglė Noreikaitė pateikė prašymą.
2. Kontaktinis el. paštas: egles.demo@example.org.
```

**Reply**

```text
1. Eglės Noreikaitės prašymas peržiūrėtas.
2. Atsakymas pateikiamas pagal 1 punktą.
```

## Protect and link the mentions

1. Start PrivaPII and choose **Create workspace**. Save it as `demo.sqlite` in a local folder. Import both text files into this workspace.
2. Open the application in the workspace's document dropdown. Select **Detect**. Check that the email is selected for protection. In **Rules only**, select the entire name `Eglė Noreikaitė` in the source and choose **Mark selected text**. Select the new finding, choose **Edit category**, select `PER` and confirm. If the full name is already a `PER` finding, use it.
3. Repeat for `Eglės Noreikaitės` in the reply. Open **Review people**, select the application mention and choose **Set selected mention as target**. Select the reply mention and choose **Link selected mentions to target**. Confirm the link. Both rows should now display the same entity ID.
4. Use **Standard** for both documents. In **Categories and profiles**, select **Standard**, press **Load profile**, and confirm. Keep `PER` and `EMAIL` selected and `DATE` unchecked. Turn on **Expose linked person IDs** for this test. In each document, choose **Pseudonymize → Save reviewed export**, select **Markdown**, then choose **Save reviewed file**. Save the results as `document-01.md` and `document-02.md`.

In the exports, check that the name forms and the email are replaced by tokens, the date of issue remains complete and the numbered clauses are readable. The two person tokens should share the entity segment and have different form segments.

## Simulate an external result and restore it

1. In a local editor, make a new file called `returned.md`. Copy the reply's pseudonymized text above the application's pseudonymized text. Copy one intact person token again at the end. Save the result.
2. Close and reopen the same workspace. In **Restore derived text**, import `returned.md`. Use **Compare tokens**, select both original Markdown exports, and check for **three distinct expected tokens returned** and **one repeated occurrence**.
3. Choose **Preview local restoration**. Check that the reply uses `Eglės Noreikaitės`, the application uses `Eglė Noreikaitė` and the repeated token restores to its recorded form. The email should also reappear. Save this copy locally with **Save restored file**.
4. As a separate check, alter one character inside a token and preview again. Restoration should report an error. Undo the edit to continue.

## Send useful feedback

Record the input format, detection mode, selected profile and the step where you got stuck. For each issue, describe what you expected and what happened. Useful examples include a name left partially visible, a useful date hidden, a confusing button, a broken table or a token that failed to restore. Use fictional or redacted examples in feedback. Keep originals, restored files, vaults and passphrases local.
