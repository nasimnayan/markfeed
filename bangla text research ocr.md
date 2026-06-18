Technical Engineering Framework for Offline Bangla-English Document Digitization Systems

The engineering of an offline, self-hosted document digitization system for the Bangla and English languages requires a sophisticated integration of computer vision, deep learning sequence modeling, and linguistic heuristics. Unlike Western scripts, which are characterized by discrete, linear character sequences, the Bangla script—as part of the Brahmic family—presents unique topological challenges. These include a continuous horizontal headline known as the Matra, complex consonant-vowel clusters (graphemes), and vertical stacking of characters (Juktoborno) [cite: 1, 2, 3]. Developing a system that achieves high accuracy on diverse inputs, ranging from high-resolution scanned PDFs to noisy, perspective-distorted camera photos, demands a modular architecture where each stage—from initial binarization to final structured export—is optimized for script-specific nuances.

Comparative Analysis of Open-Source OCR Engines

The choice of a primary recognition engine is the most significant architectural decision in an offline pipeline. In the current open-source landscape, the evaluation focuses on Tesseract, EasyOCR, and PaddleOCR, each representing a distinct stage in the evolution of character recognition technology.

Tesseract OCR: The LSTM Sequence Decoder

Tesseract has served as the baseline for open-source OCR since its release by HP in the 1980s. Its current iteration, version 5.x, utilizes a Long Short-Term Memory (LSTM) based neural engine that treats text recognition as a sequence-to-sequence problem [cite: 4, 5]. Internally, Tesseract 5 employs a Convolutional Recurrent Neural Network (CRNN) architecture, where image features are extracted and fed into a bi-directional LSTM. The output is then decoded using a Connectionist Temporal Classification (CTC) layer, which determines the most probable character sequence without requiring explicit segmentation of individual glyphs [cite: 4, 6].

For Bangla, Tesseract’s performance is highly dependent on the quality of the "tessdata\_best" models. While it supports over 100 languages, its legacy layout analysis tools often struggle with the Matra-driven connectivity of Bangla words, leading to "word splitting" errors where a single word is interpreted as multiple fragments [cite: 7, 8]. However, Tesseract remains the most efficient engine for CPU-only environments, with a binary footprint of approximately 10MB to 20MB, making it ideal for edge deployment where latency budgets are measured in milliseconds rather than seconds [cite: 9, 10].

EasyOCR: Character Region Awareness

EasyOCR, built on the PyTorch framework, represents a modern deep-learning approach. It utilizes the CRAFT (Character Region Awareness for Text Detection) algorithm for localization and a ResNet-based CRNN for recognition [cite: 11, 12]. CRAFT is particularly effective for noisy documents because it predicts "character affinity" scores, allowing it to detect text in non-linear orientations, such as curved or tilted lines found in phone-captured images [cite: 11, 13].

Research indicates that EasyOCR consistently outperforms Tesseract on the "Bangla-CrossHair" dataset, especially in scenarios involving motion blur and perspective warping [cite: 9, 11]. The primary drawback of EasyOCR is its computational overhead. It requires approximately 500MB of dependencies and is heavily optimized for GPU environments. In an offline CPU-only configuration, throughput can drop significantly, often processing only 8 pages per minute compared to Tesseract’s 25 [cite: 9, 12].

PaddleOCR: The Multimodal Parsing Paradigm

PaddleOCR, developed by Baidu, is currently the industrial standard for open-source document digitization. It employs a modular "PP-OCR" pipeline consisting of detection (DBNet), orientation classification, and recognition (SVTR) [cite: 4, 10]. The Spatial Visual Transformer (SVTR) recognition model moves away from LSTMs, using transformer encoder layers to capture long-range contextual relationships within a text image. This is particularly beneficial for the Bangla script, where the recognition of a base character often depends on the presence of modifiers (Kar or Phola) located several pixels away [cite: 4, 14].

The most recent iteration, PaddleOCR-VL (Vision-Language), utilizes a 0.9 billion parameter VLM to achieve state-of-the-art results on benchmarks like OmniDocBench [cite: 15, 16]. It is the only open-source framework with integrated layout analysis (PP-Structure) that can natively reconstruct tables and identify reading order across complex, multi-column layouts [cite: 12, 17].

|  |  |  |  |
| --- | --- | --- | --- |
| **Metric** | **Tesseract 5.5** | **EasyOCR** | **PaddleOCR v4** |
| **Core Architecture** | LSTM + CTC | CRAFT + CRNN | DBNet + SVTR |
| **Bangla Accuracy** | Moderate (Clean text) | High (Noisy text) | SOTA (All conditions) |
| **CPU Throughput** | ~25 pages/min | ~8 pages/min | ~15 pages/min |
| **GPU Throughput** | N/A | ~60 pages/min | ~120+ pages/min |
| **Layout Awareness** | Basic (PSM modes) | None (Flat text) | Full (PP-Structure) |
| **Disk Footprint** | ~20 MB | ~500 MB | ~1.4 GB - 4 GB |

The analysis suggests that a production-grade offline system should utilize **PaddleOCR v4** as the primary engine due to its superior accuracy-to-latency ratio and native support for structured layout analysis [cite: 12, 15, 18].

Linguistic Anatomy and Script-Specific Challenges

Designing an OCR system for Bangla requires a deep understanding of its phonological and orthographic structure. The script consists of 11 vowels, 39 consonants, and over 250 compound characters (Juktoborno) [cite: 3, 19, 20].

The Matra Bridge and Zone Division

A defining feature of Bangla is the Matra—a horizontal line that runs across the top of most characters in a word. This headline creates a topological connection that confounds traditional segmentation algorithms. Most Bangla OCR research identifies a three-zone vertical structure:

1. **Upper Zone:** This region sits above the Matra and contains vowel modifiers like the 'Oi-kar' or the 'Reph' (consonant modifier) [cite: 1, 21, 22].
2. **Middle Zone:** The primary body of the character, where base consonants and vowels reside. This zone is bounded at the top by the Matra and at the bottom by an imaginary baseline [cite: 1, 3, 21].
3. **Lower Zone:** The region below the baseline, containing lower modifiers like 'U-kar' and the 'Ra-phola' [cite: 1, 2, 3].

A critical engineering step for high-accuracy Bangla recognition is "Matra-stripping." By using a horizontal projection profile, the system identifies the row with the highest pixel density (the Matra) and temporarily ignores it. This "disconnects" the characters, allowing recognition models to process individual graphemes with reduced interference from neighboring shapes [cite: 21, 22, 23].

Grapheme and Juktoborno Complexity

The complexity of Bangla is further magnified by its nearly 13,000 unique variations of graphemes [cite: 19]. Juktoborno (conjuncts) occur when two or more consonants are combined, often resulting in a shape that bears little resemblance to its constituent parts (e.g., ). An effective OCR engine must be trained on datasets that represent these compound forms as discrete classes rather than attempting to recognize individual letters within the cluster [cite: 20, 24].

Computer Vision Preprocessing Pipeline

Preprocessing is the foundation of any OCR system. For an offline system handling scanned PDFs and camera-captured photos, the pipeline must resolve geometric distortions, lighting inconsistencies, and digital noise.

Perspective and Geometric Correction

Camera-shot documents are rarely perfectly aligned with the lens, resulting in trapezoidal distortion. Resolving this requires a perspective transformation:

1. **Detection:** A Sobel or Canny edge detector identifies the document's edges [cite: 25].
2. **Contour Analysis:** The system identifies the four corners of the largest quadrilateral contour [cite: 26, 27].
3. **Homography Matrix:** A 3x3 transformation matrix is computed to map the distorted coordinates to a standard rectangular grid [cite: 28].

Deskewing Algorithms

Skew, even at a 1-degree angle, can cause line-segmentation failures. For Bangla, where the Matra provides a strong horizontal signal, Radon-based deskewing is particularly effective. By calculating the Radon transform (integrating pixel intensities along various angles), the system identifies the angle that yields the highest peak in the sinogram, which corresponds to the true orientation of the Matra lines [cite: 1, 27].

Local Adaptive Binarization: The Sauvola Method

Global binarization (Otsu's method) calculates a single threshold for the entire image. While efficient, it fails on documents with gradients or shadows, often erasing thin text strokes in bright areas or merging text in dark areas [cite: 3, 29, 30].

For Bangla, preserving the thin Matra and Kar modifiers is essential. Sauvola's binarization, a local adaptive method, calculates a threshold  for every pixel based on the local mean  and standard deviation :Here,  is the dynamic range of standard deviation (usually 128), and  is a sensitivity parameter (typically 0.2 to 0.5). Sauvola binarization significantly improves the preservation of connectivity in Bangla words, leading to a measurable reduction in Character Error Rate (CER) [cite: 29, 31, 32].

Adaptive Shadow Removal and Contrast Enhancement

Shadows from phone cameras are common in self-hosted digitization workflows. The system should implement an illumination-reflectance model (). By converting the image to the LAB color space and applying Multi-Scale Retinex (MSR) to the 'L' (lightness) channel, the system can estimate the background illumination field and subtract it, effectively "flattening" shadows without altering text color [cite: 33, 34, 35]. Contrast-Limited Adaptive Histogram Equalization (CLAHE) should follow this to ensure that faded text in old documents becomes legible for the OCR engine [cite: 33, 36, 37].

Document Layout Analysis and Table Extraction

Beyond character recognition, the system must understand document structure. Document Layout Analysis (DLA) involves segmenting the page into semantic regions: headings, paragraphs, images, and tables.

Deep Learning-Based Layout Detection

Rule-based layout analysis (like Tesseract's legacy algorithms) fails on documents with complex, overlapping regions. Modern systems use object detection architectures:

* **RT-DETR / Mask R-CNN:** Models trained on datasets like DocLayNet can predict bounding boxes for paragraphs and tables with high confidence [cite: 26, 38, 39].
* **PP-Structure:** Part of the PaddleOCR ecosystem, this module is purpose-built for identifying reading order and table regions in a single pass [cite: 4, 12, 17].

Table Extraction Strategies

Table extraction is a multi-phase problem consisting of detection, structure recognition, and data extraction.

PDF-Native Rule-Based Systems

For "born-digital" PDFs where text positions are known, rule-based tools are superior due to their speed and precision:

* **Camelot (Lattice mode):** Uses morphological transformations to detect visible grid lines [cite: 40].
* **Camelot (Stream mode):** Uses whitespace alignment and the "gutter" between columns to infer structure in borderless tables [cite: 40].

Image-Based Table Transformer (TATR)

For scanned images or photos where grid lines may be broken or non-existent, Table Transformer (TATR) is the current SOTA [cite: 41, 42]. Based on the DEtection TRansformer (DETR), TATR predicts the logical grid structure (rows, columns, and spanning cells) directly from visual features [cite: 41, 42]. Unlike rule-based systems, TATR can handle merged cells and hierarchical headers (e.g., a header spanning three columns) by reasoning about the spatial relational context of the data [cite: 38, 41, 43].

Grid-Based Layout Reconstruction Algorithm

Once cell bounding boxes are identified, they must be mapped to a logical row-column matrix for Excel export. A robust offline algorithm follows these steps:

1. **Normalization:** Map all coordinates to a resolution-independent scale  [cite: 44].
2. **Vertical/Horizontal Clustering:** Use a 1D clustering algorithm (like DBSCAN) on the Y-coordinates of cell boxes to group them into rows. Perform the same on X-coordinates to identify columns [cite: 27, 45].
3. **Conflict Resolution:** For spanning cells, identify boxes that intersect multiple logical row/column clusters.
4. **Cell-Level OCR:** Perform a high-precision OCR pass on each isolated cell crop. Padding the crop by 5-10 pixels ensures that characters touching the border are not clipped [cite: 26, 27, 43].

Output and Export System Design

The system's export layer must transform internal OCR data (bounding boxes, text, confidence) into standardized, user-facing formats.

hOCR: The Intermediate Data Backbone

The system should utilize the hOCR standard—an open XHTML format—as its primary internal representation. hOCR encodes structural metadata (ocr\_page, ocr\_carea, ocr\_line, ocrx\_word) alongside bounding box coordinates and confidence scores [cite: 46, 47]. This allows the system to remain modular; a single hOCR file can be the source for PDFs, JSONs, and Markdown exports.

Searchable PDF Generation via OCRmyPDF

Generating a searchable PDF requires overlaying a transparent text layer on the original document image. OCRmyPDF is the industry standard for this task. It handles:

* **Rasterization:** Converting PDF pages to high-DPI images (typically 300-600 DPI) for OCR [cite: 8, 48, 49].
* **Archival Compliance:** Outputting to the PDF/A standard for long-term digital preservation [cite: 8].
* **Metadata Retention:** Ensuring original file signatures and document properties are not lost during the OCR process [cite: 8].

Structured JSON and Excel Export

For data-centric applications, the system must export a hierarchical JSON structure that preserves the relationship between text blocks and their confidence scores [cite: 50, 51]. Excel export is achieved by passing the reconstructed logical grid to the pandas library, using to\_excel() with the openpyxl engine [cite: 45, 52].

Markdown and Semantic Chunking for Knowledge Bases

For RAG (Retrieval-Augmented Generation) systems, the output should be chunked according to document hierarchy:

* **Structure-Aware Chunking:** Breaking text at identified headings (H1, H2) rather than arbitrary token counts [cite: 53, 54, 55].
* **Table Inlining:** Representing tables using Markdown pipe syntax (| Col |) to ensure they remain meaningful when retrieved by downstream search engines [cite: 56, 57].
* **Contextual Breadcrumbs:** Prepending the parent heading hierarchy to each chunk (e.g., # Section 1 > ## Sub-section A) to prevent semantic loss during retrieval [cite: 58, 59].

Non-LLM OCR Quality Validation

Measuring the quality of the digitization process without cloud-based LLMs requires deterministic metrics and rule-based linguistic filters.

Quantitative Accuracy Metrics

Two primary metrics serve as the technical gold standard:

1. **Character Error Rate (CER):** Calculated using the Levenshtein distance between the OCR output and the ground truth.where  is substitutions,  is insertions,  is deletions, and  is the total character count [cite: 60, 61, 62].
2. **Word Error Rate (WER):** Similar to CER but calculated at the word level. WER is more intuitive for business applications where word-level accuracy is critical for search indexing [cite: 60, 61].

Confidence Scoring and Error Signals

Every word recognized by modern engines (Tesseract, PaddleOCR) returns a probability score (0-100). The system should implement threshold-based flags:

* **Confidence Gate:** Any word with a confidence score below 75 is flagged for a secondary ensemble recognizer or human manual review [cite: 43, 44, 63].
* **Layout Consistency Check:** If a recognized word's character count exceeds the theoretical capacity of its bounding box (e.g., 20 characters in a 10-pixel box), a "segmentation hallucination" flag is raised [cite: 44, 64].

Post-OCR Rule-Based Validation

Linguistic heuristics can detect systemic recognition errors:

* **Juktoborno Regex:** Ensuring that character clusters follow valid Bangla phonology (e.g., a 'Chandrabindu' nasalization mark only appearing over certain base characters) [cite: 20, 24].
* **SymSpell Fuzzy Correction:** A symmetric delete algorithm that uses frequency dictionaries to correct common OCR misreads (e.g., mistaking the 'E-kar' modifier for a vertical bar) [cite: 65].
* **Unicode Normalization:** Forcing all output to Unicode NFC (Canonical Composition) to ensure consistency across search systems, as Bangla features multiple ways to encode the same visual character [cite: 61].

Proposed Modular System Architecture

The following architecture defines an end-to-end offline pipeline, separating image processing from high-level data structuring.

1. Ingestion Layer

Supports multiple formats: Scanned PDF, JPEG, PNG, TIFF.

2. Preprocessing Module (OpenCV / Scikit-Image)

* **Mandatory:** Grayscale conversion, Radon Deskewing, Sauvola Binarization.
* **Optional (Photo-Specific):** Perspective correction, Retinex shadow removal.

3. Layout Analysis Module (PaddleOCR PP-Structure)

Identifies "Document Regions": Text (Paragraph/Heading), Tables, Figures, Separators. Determines reading order for multi-column documents.

4. OCR Recognition Module (PaddleOCR SVTR)

* **Execution:** Processes each region identified by the Layout Analysis module.
* **Ensemble Strategy:** If confidence < 75, re-process the crop using Tesseract and choose the result with the higher internal confidence.

5. Post-Processing & Validation Module (SymSpell / Rule Engine)

* Apply SymSpell dictionary correction.
* Run script-specific validation (Juktoborno/Matra connectivity).
* Flag low-confidence blocks for the human-in-the-loop (HITL) queue.

6. Structured Output (hOCR / JSON)

Generates the internal XML-based representation containing all positional and confidence data.

7. Export Layer (Multiple Drivers)

* **Driver A:** OCRmyPDF -> Searchable PDF/A.
* **Driver B:** Pandas -> Excel/CSV (via Table Grid Reconstruction).
* **Driver C:** python-docx -> Word Documents (via Reading Order blocks).
* **Driver D:** Markdown-Chunker -> Knowledge Base (Semantic chunks).

Engineering Trade-offs and Performance Considerations

Designing a self-hosted system involves critical balances between precision, computational requirements, and script-specific fidelity.

Latency vs. Accuracy

Utilizing a deep learning layout analyzer (PP-Structure) and a transformer-based recognizer (SVTR) provides the highest accuracy but introduces latency. While Tesseract can OCR a page in ~40ms on a standard CPU, a full deep-learning pipeline may take ~1.0 second per page [cite: 9, 10, 15]. For batch processing millions of archived documents, a high-throughput Tesseract cluster might be necessary, but for high-stakes digitization (legal/medical), the PaddleOCR accuracy is indispensable [cite: 12, 66].

Matra Preservation vs. Denoising

Aggressive denoising filters can inadvertently "erode" the Matra line or small vowel modifiers in Bangla, causing words to be segmented into meaningless fragments [cite: 1, 3, 29]. The system must use **Sauvola Binarization** as a non-negotiable step to maintain the connectivity required for accurate Indic sequence decoding [cite: 29, 30, 32].

Hardware Resource Allocation

Running a transformer-based system offline requires significant VRAM. While basic OCR can run on 2GB, the full system (Layout Detection + SVTR + Table Transformer) requires 6GB to 8GB of VRAM (e.g., an NVIDIA RTX 3060/4060) to maintain a throughput of 120 pages per minute [cite: 67, 68, 69]. On CPU-only servers, the system should fall back to "PaddleOCR-Lite" models to avoid processing bottlenecks [cite: 15].

Actionable Recommendations for System Implementation

For a high-accuracy Bangla-English offline digitization system, the following stack is recommended:

1. **Core Engine:** **PaddleOCR v4** (SVTR) using the PaddlePaddle backend. It provides the best baseline accuracy for Indic scripts and handles mixed layouts natively [cite: 12, 17, 18].
2. **Preprocessing Strategy:** Implement **Sauvola local thresholding** and **Radon deskewing**. These techniques are specifically tuned to preserve the Matra line in Bangla [cite: 29, 31, 32].
3. **Table Extraction:** For scanned documents, deploy the **Table Transformer (TATR)**. It is significantly more robust than rule-based systems for handling complex, borderless, or merged tables [cite: 41, 42, 43].
4. **Linguistic Layer:** Use **SymSpell** with a custom frequency dictionary derived from a large-scale Bangla corpus (e.g., 100M+ words from the OSCAR dataset). This ensures spelling correction without the latency of an LLM [cite: 65, 70, 71].
5. **Data Standard:** Adopt **hOCR** as the universal intermediate format. It bridges the gap between raw OCR detection and final output drivers for PDF, Word, and Excel [cite: 46, 50].

By following this architectural framework, an offline system can achieve a Character Error Rate (CER) below 2% for clean printed text and below 5% for noisy scans, rivaling the performance of proprietary cloud-based OCR services while maintaining complete data privacy and self-hosting capabilities.

--------------------------------------------------------------------------------

1. A Complete Workflow for Development of Bangla OCR - ResearchGate, [https://www.researchgate.net/publication/222109100\_A\_Complete\_Workflow\_for\_Development\_of\_Bangla\_OCR](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.researchgate.net%2Fpublication%2F222109100_A_Complete_Workflow_for_Development_of_Bangla_OCR)
2. A survey on optical character recognition for Bangla and Devanagari scripts - Indian Academy of Sciences, [https://www.ias.ac.in/article/fulltext/sadh/038/01/0133-0168](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.ias.ac.in%2Farticle%2Ffulltext%2Fsadh%2F038%2F01%2F0133-0168)
3. A Complete Workflow for Development of Bangla OCR - arXiv, [https://arxiv.org/pdf/1204.1198](https://www.google.com/url?sa=E&q=https%3A%2F%2Farxiv.org%2Fpdf%2F1204.1198)
4. Technical Analysis of Modern Non-LLM OCR Engines | IntuitionLabs, [https://intuitionlabs.ai/articles/non-llm-ocr-technologies](https://www.google.com/url?sa=E&q=https%3A%2F%2Fintuitionlabs.ai%2Farticles%2Fnon-llm-ocr-technologies)
5. Technical Analysis of Modern Non-LLM OCR Engines - IntuitionLabs, [https://intuitionlabs.ai/pdfs/technical-analysis-of-modern-non-llm-ocr-engines.pdf](https://www.google.com/url?sa=E&q=https%3A%2F%2Fintuitionlabs.ai%2Fpdfs%2Ftechnical-analysis-of-modern-non-llm-ocr-engines.pdf)
6. Building a Modern OCR Pipeline. Optical Character Recognition (OCR)… | by Kiamars Mirzaee | Medium, [https://medium.com/@kiamars.mirzaee/building-a-modern-ocr-pipeline-d2e57bcf2c10](https://www.google.com/url?sa=E&q=https%3A%2F%2Fmedium.com%2F%40kiamars.mirzaee%2Fbuilding-a-modern-ocr-pipeline-d2e57bcf2c10)
7. Tesseract vs EasyOCR: A Comparative Analysis | PDF | Optical Character Recognition | Computing - Scribd, [https://www.scribd.com/document/915037187/Tesseract-vs-EasyOCR-Utilities2-1](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.scribd.com%2Fdocument%2F915037187%2FTesseract-vs-EasyOCR-Utilities2-1)
8. Introduction — ocrmypdf 17.6.0 documentation, [https://ocrmypdf.readthedocs.io/en/latest/introduction.html](https://www.google.com/url?sa=E&q=https%3A%2F%2Focrmypdf.readthedocs.io%2Fen%2Flatest%2Fintroduction.html)
9. Tesseract vs EasyOCR: I Tested Both (2025) | Real Results | CodeSOTA, [https://www.codesota.com/ocr/tesseract-vs-easyocr](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.codesota.com%2Focr%2Ftesseract-vs-easyocr)
10. PaddleOCR vs Tesseract vs EasyOCR: OCR Speed and Accuracy 2026 | CodeSOTA, [https://codesota.com/ocr/paddleocr-vs-tesseract](https://www.google.com/url?sa=E&q=https%3A%2F%2Fcodesota.com%2Focr%2Fpaddleocr-vs-tesseract)
11. Performance Analysis of Tesseract and EasyOCR for Bangla Optical Character Recognition on the Novel Bangla CrossHair Dataset - ResearchGate, [https://www.researchgate.net/publication/390564089\_Performance\_Analysis\_of\_Tesseract\_and\_EasyOCR\_for\_Bangla\_Optical\_Character\_Recognition\_on\_the\_Novel\_Bangla\_CrossHair\_Dataset](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.researchgate.net%2Fpublication%2F390564089_Performance_Analysis_of_Tesseract_and_EasyOCR_for_Bangla_Optical_Character_Recognition_on_the_Novel_Bangla_CrossHair_Dataset)
12. PaddleOCR vs Tesseract vs EasyOCR: OCR Model Comparison - GIGAGPU, [https://gigagpu.com/paddleocr-vs-tesseract-vs-easyocr/](https://www.google.com/url?sa=E&q=https%3A%2F%2Fgigagpu.com%2Fpaddleocr-vs-tesseract-vs-easyocr%2F)
13. OCR Engines Comparison and Findings - Fedora Discussion, [https://discussion.fedoraproject.org/t/ocr-engines-comparison-and-findings/185970](https://www.google.com/url?sa=E&q=https%3A%2F%2Fdiscussion.fedoraproject.org%2Ft%2Focr-engines-comparison-and-findings%2F185970)
14. OCR text recognition with/without deep learning in comparison - BLU DELTA, [https://www.bludelta.de/en/ocr-and-deepocr-in-comparison/](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.bludelta.de%2Fen%2Focr-and-deepocr-in-comparison%2F)
15. Unlocking high-performance document parsing of PaddleOCR VL 1 5 on AMD GPUs, [https://www.amd.com/en/developer/resources/technical-articles/2026/unlocking-high-performance-document-parsing-of-paddleocr-vl-1-5-.html](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.amd.com%2Fen%2Fdeveloper%2Fresources%2Ftechnical-articles%2F2026%2Funlocking-high-performance-document-parsing-of-paddleocr-vl-1-5-.html)
16. PaddleOCR-VL-1.5 just dropped and it's crushing OCR benchmarks right now - Reddit, [https://www.reddit.com/r/aicuriosity/comments/1qq9re5/paddleocrvl15\_just\_dropped\_and\_its\_crushing\_ocr/](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.reddit.com%2Fr%2Faicuriosity%2Fcomments%2F1qq9re5%2Fpaddleocrvl15_just_dropped_and_its_crushing_ocr%2F)
17. PaddleOCR vs Tesseract: Which is the best open source OCR? - Koncile, [https://www.koncile.ai/en/ressources/paddleocr-analyse-avantages-alternatives-open-source](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.koncile.ai%2Fen%2Fressources%2Fpaddleocr-analyse-avantages-alternatives-open-source)
18. Best OCR Model 2026: PaddleOCR-VL-1.6 Leads (Ranked Benchmarks) | CodeSOTA, [https://www.codesota.com/ocr](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.codesota.com%2Focr)
19. Pipeline Enabling Zero-shot Classification for Bangla Handwritten Grapheme, [https://aclanthology.org/2023.banglalp-1.4/](https://www.google.com/url?sa=E&q=https%3A%2F%2Faclanthology.org%2F2023.banglalp-1.4%2F)
20. (PDF) A hybrid approach to Bangla handwritten OCR: combining YOLO and an advanced CNN - ResearchGate, [https://www.researchgate.net/publication/392908471\_A\_hybrid\_approach\_to\_Bangla\_handwritten\_OCR\_combining\_YOLO\_and\_an\_advanced\_CNN](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.researchgate.net%2Fpublication%2F392908471_A_hybrid_approach_to_Bangla_handwritten_OCR_combining_YOLO_and_an_advanced_CNN)
21. A Complete Bangla OCR System for Printed Chracters - UAP, [https://www.uap-bd.edu/jcit\_papers/vol-1\_no-1/JCIT-100707.pdf](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.uap-bd.edu%2Fjcit_papers%2Fvol-1_no-1%2FJCIT-100707.pdf)
22. Bangla Text Recognition from Video Sequence: A New Focus - arXiv, [https://arxiv.org/pdf/1401.1190](https://www.google.com/url?sa=E&q=https%3A%2F%2Farxiv.org%2Fpdf%2F1401.1190)
23. Bangla optical character recognition through segmentation using curvature distance and multilayer perceptron algorithm - ResearchGate, [https://www.researchgate.net/publication/316906791\_Bangla\_optical\_character\_recognition\_through\_segmentation\_using\_curvature\_distance\_and\_multilayer\_perceptron\_algorithm](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.researchgate.net%2Fpublication%2F316906791_Bangla_optical_character_recognition_through_segmentation_using_curvature_distance_and_multilayer_perceptron_algorithm)
24. (PDF) A Hybrid Approach to Bangla Handwritten OCR: Combining YOLO and an Advanced CNN - ResearchGate, [https://www.researchgate.net/publication/385953162\_A\_Hybrid\_Approach\_to\_Bangla\_Handwritten\_OCR\_Combining\_YOLO\_and\_an\_Advanced\_CNN](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.researchgate.net%2Fpublication%2F385953162_A_Hybrid_Approach_to_Bangla_Handwritten_OCR_Combining_YOLO_and_an_Advanced_CNN)
25. A Deep Learning Method for Document Shadow Removal with Sobel Prior under Mask Supervision, [https://ojs.aaai.org/index.php/AAAI/article/view/35333/37488](https://www.google.com/url?sa=E&q=https%3A%2F%2Fojs.aaai.org%2Findex.php%2FAAAI%2Farticle%2Fview%2F35333%2F37488)
26. Document Layout Detection and OCR With Detectron2 - Analytics Vidhya, [https://www.analyticsvidhya.com/blog/2021/05/document-layout-detection-and-ocr-with-detectron2/](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.analyticsvidhya.com%2Fblog%2F2021%2F05%2Fdocument-layout-detection-and-ocr-with-detectron2%2F)
27. Detect Table in an Image in Python: Complete Guide - Cloudinary, [https://cloudinary.com/guides/image-effects/detect-table-in-image-python](https://www.google.com/url?sa=E&q=https%3A%2F%2Fcloudinary.com%2Fguides%2Fimage-effects%2Fdetect-table-in-image-python)
28. Enhancement of Bengali OCR by Specialized Models and Advanced Techniques for Diverse Document Types, [https://openaccess.thecvf.com/content/WACV2024W/WVLL/papers/Rabby\_Enhancement\_of\_Bengali\_OCR\_by\_Specialized\_Models\_and\_Advanced\_Techniques\_WACVW\_2024\_paper.pdf](https://www.google.com/url?sa=E&q=https%3A%2F%2Fopenaccess.thecvf.com%2Fcontent%2FWACV2024W%2FWVLL%2Fpapers%2FRabby_Enhancement_of_Bengali_OCR_by_Specialized_Models_and_Advanced_Techniques_WACVW_2024_paper.pdf)
29. Result of applying the Otsu 2 and the Sauvola 1 binarization algorithms... - ResearchGate, [https://www.researchgate.net/figure/Result-of-applying-the-Otsu-2-and-the-Sauvola-1-binarization-algorithms-on-a\_fig1\_221253734](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.researchgate.net%2Ffigure%2FResult-of-applying-the-Otsu-2-and-the-Sauvola-1-binarization-algorithms-on-a_fig1_221253734)
30. An Analytical Study of different Document Image Binarization Methods - arXiv, [https://arxiv.org/pdf/1501.07862](https://www.google.com/url?sa=E&q=https%3A%2F%2Farxiv.org%2Fpdf%2F1501.07862)
31. Evaluation of Binarization Methods for Aged Printed Myanmar Documents, [https://meral.edu.mm/record/4430/files/Evaluation%20of%20Binarization%20Methods%20for%20Aged%20Printed%20Myanmar%20Documents.pdf](https://www.google.com/url?sa=E&q=https%3A%2F%2Fmeral.edu.mm%2Frecord%2F4430%2Ffiles%2FEvaluation%2520of%2520Binarization%2520Methods%2520for%2520Aged%2520Printed%2520Myanmar%2520Documents.pdf)
32. An Improved Sauvola Approach on Document Images Binarization - Journal of Telecommunication, Electronic and Computer Engineering (JTEC), [https://jtec.utem.edu.my/jtec/article/download/2548/2826](https://www.google.com/url?sa=E&q=https%3A%2F%2Fjtec.utem.edu.my%2Fjtec%2Farticle%2Fdownload%2F2548%2F2826)
33. Enhancing Images: Adaptive Shadow Correction Using OpenCV - Edge AI and Vision Alliance, [https://www.edge-ai-vision.com/2026/02/enhancing-images-adaptive-shadow-correction-using-opencv/](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.edge-ai-vision.com%2F2026%2F02%2Fenhancing-images-adaptive-shadow-correction-using-opencv%2F)
34. how can i remove shadow from image completely? : r/computervision - Reddit, [https://www.reddit.com/r/computervision/comments/1dltgqw/how\_can\_i\_remove\_shadow\_from\_image\_completely/](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.reddit.com%2Fr%2Fcomputervision%2Fcomments%2F1dltgqw%2Fhow_can_i_remove_shadow_from_image_completely%2F)
35. Leveraging Contrast Information for Efficient Document Shadow Removal Identify applicable funding agency here. If none, delete this. - arXiv, [https://arxiv.org/html/2504.00385v1](https://www.google.com/url?sa=E&q=https%3A%2F%2Farxiv.org%2Fhtml%2F2504.00385v1)
36. Evaluation of OCR Engines for Logistics Documents: Accuracy, Preprocessing and Cloud Integration - kth .diva, [https://kth.diva-portal.org/smash/get/diva2:2020551/FULLTEXT01.pdf](https://www.google.com/url?sa=E&q=https%3A%2F%2Fkth.diva-portal.org%2Fsmash%2Fget%2Fdiva2%3A2020551%2FFULLTEXT01.pdf)
37. Shadow Removal - Kaggle, [https://www.kaggle.com/code/faizanaliabdulali/shadow-removal](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.kaggle.com%2Fcode%2Ffaizanaliabdulali%2Fshadow-removal)
38. Docling: An Efficient Open-Source Toolkit for AI-driven Document Conversion - arXiv, [https://arxiv.org/html/2501.17887v1](https://www.google.com/url?sa=E&q=https%3A%2F%2Farxiv.org%2Fhtml%2F2501.17887v1)
39. Analyzing Document Layout with LayoutParser - Towards Data Science, [https://towardsdatascience.com/analyzing-document-layout-with-layoutparser-ed24d85f1d44/](https://www.google.com/url?sa=E&q=https%3A%2F%2Ftowardsdatascience.com%2Fanalyzing-document-layout-with-layoutparser-ed24d85f1d44%2F)
40. OCR Table to Excel: Best Ways to Extract Tabular Data - Lido, [https://www.lido.app/blog/ocr-table-to-excel](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.lido.app%2Fblog%2Focr-table-to-excel)
41. Table Detection and Transformation Using TATR (Table Transform... - E2E Networks, [https://www.e2enetworks.com/blog/table-detection-and-transformation-using-tatr-table-transformer-using-tatr-on-e2e-cloud](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.e2enetworks.com%2Fblog%2Ftable-detection-and-transformation-using-tatr-table-transformer-using-tatr-on-e2e-cloud)
42. We improved table extraction in DocParse with a new AI model - Aryn, [https://www.aryn.ai/post/we-improved-table-extraction-in-docparse-with-a-new-ai-model](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.aryn.ai%2Fpost%2Fwe-improved-table-extraction-in-docparse-with-a-new-ai-model)
43. Extracts structured tables from balance sheets, 10-Ks, and scanned financial PDFs using layout-aware OCR and transformer parsers. Preserves row and column hierarchy and exports clean CSV, JSON, and pandas DataFrames. · GitHub, [https://github.com/dakshjain-1616/Table-Extraction-from-Financial-Documents-By-NEO](https://www.google.com/url?sa=E&q=https%3A%2F%2Fgithub.com%2Fdakshjain-1616%2FTable-Extraction-from-Financial-Documents-By-NEO)
44. Word and Cell Level Bounding Boxes Are Now Generally Available | Pulse AI, [https://www.runpulse.com/blog/word-and-cell-level-bounding-boxes-are-now-generally-available](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.runpulse.com%2Fblog%2Fword-and-cell-level-bounding-boxes-are-now-generally-available)
45. Extract Table Fields from Image to Excel with Python OCR - AskPython, [https://www.askpython.com/resources/extract-fields-image-excel-ocr](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.askpython.com%2Fresources%2Fextract-fields-image-excel-ocr)
46. hOCR - Grokipedia, [https://grokipedia.com/page/HOCR](https://www.google.com/url?sa=E&q=https%3A%2F%2Fgrokipedia.com%2Fpage%2FHOCR)
47. Parsing hOCR to JSON with Python - Stack Overflow, [https://stackoverflow.com/questions/51421283/parsing-hocr-to-json-with-python](https://www.google.com/url?sa=E&q=https%3A%2F%2Fstackoverflow.com%2Fquestions%2F51421283%2Fparsing-hocr-to-json-with-python)
48. Convert Scanned PDFs to Searchable PDFs Using Python: Full Guide, [https://python.plainenglish.io/convert-scanned-pdfs-to-searchable-using-python-full-guide-7742c633ecf5](https://www.google.com/url?sa=E&q=https%3A%2F%2Fpython.plainenglish.io%2Fconvert-scanned-pdfs-to-searchable-using-python-full-guide-7742c633ecf5)
49. Create OCR-Processed PDFs In 2 Steps - Mindee, [https://www.mindee.com/blog/create-ocrized-pdfs-in-2-steps](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.mindee.com%2Fblog%2Fcreate-ocrized-pdfs-in-2-steps)
50. Export OCR Results to JSON - Python | LEADTOOLS SDK Tutorials Help, [https://www.leadtools.com/help/sdk/tutorials/python-export-ocr-results-to-json.html](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.leadtools.com%2Fhelp%2Fsdk%2Ftutorials%2Fpython-export-ocr-results-to-json.html)
51. How to Extract Data from Documents with Python: A Step-by-Step Guide Using Docling, [https://blog.dataengineerthings.org/how-to-extract-data-from-documents-with-python-a-step-by-step-guide-using-docling-8360264f1e87](https://www.google.com/url?sa=E&q=https%3A%2F%2Fblog.dataengineerthings.org%2Fhow-to-extract-data-from-documents-with-python-a-step-by-step-guide-using-docling-8360264f1e87)
52. Totally out of hand excel model based on historical power grid data. Where do I start in python? - Reddit, [https://www.reddit.com/r/learnpython/comments/1arci3s/totally\_out\_of\_hand\_excel\_model\_based\_on/](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.reddit.com%2Fr%2Flearnpython%2Fcomments%2F1arci3s%2Ftotally_out_of_hand_excel_model_based_on%2F)
53. Chunk and Vectorize by Document Layout (Document Layout Skill) - Azure AI Search | Microsoft Learn, [https://learn.microsoft.com/en-us/azure/search/search-how-to-semantic-chunking](https://www.google.com/url?sa=E&q=https%3A%2F%2Flearn.microsoft.com%2Fen-us%2Fazure%2Fsearch%2Fsearch-how-to-semantic-chunking)
54. What is Document Chunking Strategies? - LlamaIndex, [https://www.llamaindex.ai/glossary/document-chunking-strategies](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.llamaindex.ai%2Fglossary%2Fdocument-chunking-strategies)
55. markdown-chunker - PyPI, [https://pypi.org/project/markdown-chunker/](https://www.google.com/url?sa=E&q=https%3A%2F%2Fpypi.org%2Fproject%2Fmarkdown-chunker%2F)
56. Tokenizer-Aware Markdown Chunking That Doesn't Shred Tables - DEV Community, [https://dev.to/gabrielanhaia/tokenizer-aware-markdown-chunking-that-doesnt-shred-tables-3kd7](https://www.google.com/url?sa=E&q=https%3A%2F%2Fdev.to%2Fgabrielanhaia%2Ftokenizer-aware-markdown-chunking-that-doesnt-shred-tables-3kd7)
57. ChunkNorris: A High-Performance and Low-Energy Approach to PDF Parsing and Chunking - arXiv, [https://arxiv.org/html/2602.00010v1](https://www.google.com/url?sa=E&q=https%3A%2F%2Farxiv.org%2Fhtml%2F2602.00010v1)
58. Layout-Aware Chunking for RAG: Why Document Structure Decides Retrieval - global blog, [https://koreadeep.com/en/blog/layout-aware-chunking-rag](https://www.google.com/url?sa=E&q=https%3A%2F%2Fkoreadeep.com%2Fen%2Fblog%2Flayout-aware-chunking-rag)
59. Structure-aware / Hierarchical Chunking for Markdown documents (Inspired by Docling) · Issue #3131 · HKUDS/LightRAG - GitHub, [https://github.com/HKUDS/LightRAG/issues/3131](https://www.google.com/url?sa=E&q=https%3A%2F%2Fgithub.com%2FHKUDS%2FLightRAG%2Fissues%2F3131)
60. OCR Accuracy Explained: What Impacts Performance and How to Improve It - LlamaIndex, [https://www.llamaindex.ai/blog/ocr-accuracy](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.llamaindex.ai%2Fblog%2Focr-accuracy)
61. Indic ASR evaluation: beyond WER to LLM & semantic metrics | Sarvam AI, [https://www.sarvam.ai/blogs/evaluating-indian-language-asr](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.sarvam.ai%2Fblogs%2Fevaluating-indian-language-asr)
62. bbOCR: An Open-source Multi-domain OCR Pipeline for Bengali Documents, [https://www.researchgate.net/publication/373263373\_bbOCR\_An\_Open-source\_Multi-domain\_OCR\_Pipeline\_for\_Bengali\_Documents](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.researchgate.net%2Fpublication%2F373263373_bbOCR_An_Open-source_Multi-domain_OCR_Pipeline_for_Bengali_Documents)
63. How To Use OCR Bounding Boxes | by Michael Orozco-Fletcher - Medium, [https://medium.com/@michael71314/how-to-use-ocr-bounding-boxes-c00303bc11c4](https://www.google.com/url?sa=E&q=https%3A%2F%2Fmedium.com%2F%40michael71314%2Fhow-to-use-ocr-bounding-boxes-c00303bc11c4)
64. Developing and Assessing an AI-Assisted hOCR Correction Workflow | Digital Scholarship Unit - University of Toronto, [https://digital.utsc.utoronto.ca/developing-and-assessing-ai-assisted-hocr-correction-workflow](https://www.google.com/url?sa=E&q=https%3A%2F%2Fdigital.utsc.utoronto.ca%2Fdeveloping-and-assessing-ai-assisted-hocr-correction-workflow)
65. GitHub - wolfgarbe/SymSpell: SymSpell: 1 million times faster spelling correction & fuzzy search through Symmetric Delete spelling correction algorithm, [https://github.com/wolfgarbe/symspell](https://www.google.com/url?sa=E&q=https%3A%2F%2Fgithub.com%2Fwolfgarbe%2Fsymspell)
66. Latency vs. Accuracy: The Engineering Trade-Off That Kills Sports Tech Products - Medium, [https://medium.com/@biodunbio14/latency-vs-accuracy-the-engineering-trade-off-that-kills-sports-tech-products-6656b451fe4e](https://www.google.com/url?sa=E&q=https%3A%2F%2Fmedium.com%2F%40biodunbio14%2Flatency-vs-accuracy-the-engineering-trade-off-that-kills-sports-tech-products-6656b451fe4e)
67. PaddleOCR-VL-1.6 VRAM Requirements & Cheapest GPU to Run It from $0.65/hr | Spheron, [https://www.spheron.network/tools/gpu-recommender/PaddlePaddle/PaddleOCR-VL-1.6](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.spheron.network%2Ftools%2Fgpu-recommender%2FPaddlePaddle%2FPaddleOCR-VL-1.6)
68. PaddleOCR VRAM Requirements - GIGAGPU, [https://gigagpu.com/paddleocr-vram-requirements/](https://www.google.com/url?sa=E&q=https%3A%2F%2Fgigagpu.com%2Fpaddleocr-vram-requirements%2F)
69. How to Run PaddleOCR on a Private GPU Server - GIGAGPU, [https://gigagpu.com/how-to-run-paddleocr-private-gpu/](https://www.google.com/url?sa=E&q=https%3A%2F%2Fgigagpu.com%2Fhow-to-run-paddleocr-private-gpu%2F)
70. Gold Standard Bangla OCR Dataset: An In-Depth Look at Data Preprocessing and Annotation Processes - ACL Anthology, [https://aclanthology.org/2023.emnlp-industry.44/](https://www.google.com/url?sa=E&q=https%3A%2F%2Faclanthology.org%2F2023.emnlp-industry.44%2F)
71. (PDF) A Comprehensive Bangla Spelling Checker - ResearchGate, [https://www.researchgate.net/publication/49242872\_A\_Comprehensive\_Bangla\_Spelling\_Checker](https://www.google.com/url?sa=E&q=https%3A%2F%2Fwww.researchgate.net%2Fpublication%2F49242872_A_Comprehensive_Bangla_Spelling_Checker)