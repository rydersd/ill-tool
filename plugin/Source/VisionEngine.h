//========================================================================================
//
//  IllTool Plugin -- Local Computer Vision Engine
//
//  Pure C++ CV operations on raster data from placed images.
//  No OpenCV, no cloud, no Python -- in-process math only.
//  Integrated with LearningEngine for noise detection and grouping.
//
//  Image loading via stb_image (public domain, header-only).
//
//========================================================================================

#ifndef __VISIONENGINE_H__
#define __VISIONENGINE_H__

#include <vector>
#include <string>
#include <cmath>
#include <utility>
#include <mutex>

//----------------------------------------------------------------------------------------
//  VisionEngine -- singleton providing CV operations on loaded raster images
//----------------------------------------------------------------------------------------

class VisionEngine {
public:
    /** Get the singleton instance. */
    static VisionEngine& Instance();

    //------------------------------------------------------------------------------------
    //  Image loading
    //------------------------------------------------------------------------------------

    /** Load a raster image from a file path. Converts to grayscale internally.
        Supports PNG, JPEG, BMP, TGA, PSD, GIF, HDR, PIC via stb_image.
        @param filePath  Absolute path to the image file.
        @return true if loaded successfully. */
    bool LoadImage(const char* filePath);

    /** Returns true if an image is currently loaded. */
    bool IsLoaded() const;

    /** Width of the loaded image in pixels. */
    int Width() const;

    /** Height of the loaded image in pixels. */
    int Height() const;

    //------------------------------------------------------------------------------------
    //  Edge detection
    //------------------------------------------------------------------------------------

    /** Canny edge detection on the loaded image.
        @param lowThresh   Lower hysteresis threshold (0-255).
        @param highThresh  Upper hysteresis threshold (0-255).
        @return Binary edge map (0 or 255), size = width * height. */
    std::vector<uint8_t> CannyEdges(double lowThresh = 50.0, double highThresh = 150.0);

    /** Sobel gradient magnitude thresholded to produce edges.
        @param threshold  Gradient magnitude threshold (0-255).
        @return Binary edge map (0 or 255), size = width * height. */
    std::vector<uint8_t> SobelEdges(double threshold = 128.0);

    /** Multi-scale edge detection: runs Canny at multiple thresholds and votes.
        Edges that persist across scales are structural (form edges).
        @param numScales      Number of threshold scales to test.
        @param voteThreshold  Minimum vote count to keep an edge pixel.
        @return Binary edge map (0 or 255), size = width * height. */
    std::vector<uint8_t> MultiScaleEdges(int numScales = 5, double voteThreshold = 3.0);

    //------------------------------------------------------------------------------------
    //  Feature detection -- Hough transforms
    //------------------------------------------------------------------------------------

    /** A line detected via Hough transform in polar coordinates. */
    struct HoughLine {
        double rho;     // Distance from origin to closest point on the line
        double theta;   // Angle of the normal from origin to closest point (radians)
        int    votes;   // Accumulator strength
    };

    /** Detect lines in edge image via Hough transform.
        Operates on the result of CannyEdges or SobelEdges.
        @param edges      Binary edge map (0 or 255).
        @param rhoRes     Rho resolution in pixels (default 1.0).
        @param thetaRes   Theta resolution in radians (default pi/180).
        @param threshold  Minimum accumulator votes.
        @return Vector of detected lines sorted by vote count descending. */
    std::vector<HoughLine> DetectLines(const std::vector<uint8_t>& edges,
                                        double rhoRes = 1.0,
                                        double thetaRes = M_PI / 180.0,
                                        int threshold = 50);

    /** A circle detected via Hough transform. */
    struct Circle {
        double cx, cy;   // Center coordinates
        double radius;   // Radius in pixels
        int    votes;    // Accumulator strength
    };

    /** Detect circles in edge image via Hough gradient method.
        @param edges      Binary edge map.
        @param minRadius  Minimum circle radius to detect.
        @param maxRadius  Maximum circle radius to detect.
        @param threshold  Minimum accumulator votes.
        @return Vector of detected circles sorted by vote count descending. */
    std::vector<Circle> DetectCircles(const std::vector<uint8_t>& edges,
                                       double minRadius = 5.0,
                                       double maxRadius = 100.0,
                                       int threshold = 30);

    //------------------------------------------------------------------------------------
    //  Segmentation
    //------------------------------------------------------------------------------------

    /** Flood fill from a seed point, producing a binary mask.
        Fills all connected pixels within tolerance of the seed pixel value.
        @param seedX      X coordinate of the seed point.
        @param seedY      Y coordinate of the seed point.
        @param tolerance  Maximum brightness difference from seed to fill (0-255).
        @return Binary mask (0 or 255), size = width * height. */
    std::vector<uint8_t> FloodFillMask(int seedX, int seedY, int tolerance = 10);

    /** Label connected components in a binary image.
        Uses union-find for efficient labeling.
        @param binary  Binary image (nonzero = foreground).
        @param w       Image width.
        @param h       Image height.
        @return Vector of components; each component is a vector of (x,y) pixel coords. */
    std::vector<std::vector<std::pair<int,int>>> ConnectedComponents(
        const std::vector<uint8_t>& binary, int w, int h);

    //------------------------------------------------------------------------------------
    //  Contour extraction
    //------------------------------------------------------------------------------------

    /** A contour extracted from a binary image. */
    struct Contour {
        std::vector<std::pair<double,double>> points;  // Ordered boundary points
        double area;       // Enclosed area (shoelace formula)
        double arcLength;  // Total path length
        bool   closed;     // True if contour forms a closed loop
    };

    /** Extract contours from a binary image using Moore boundary tracing.
        @param binary     Binary image (nonzero = foreground).
        @param w          Image width.
        @param h          Image height.
        @param minLength  Minimum contour point count to include.
        @return Vector of extracted contours. */
    std::vector<Contour> FindContours(const std::vector<uint8_t>& binary,
                                       int w, int h, int minLength = 10);

    //------------------------------------------------------------------------------------
    //  Active contours (snakes)
    //------------------------------------------------------------------------------------

    /** Snap a polyline to nearby edges using active contour energy minimization.
        The snake balances internal forces (smoothness) against external forces (edges).
        @param initialPath  Initial control points.
        @param alpha        Elasticity weight (continuity).
        @param beta         Stiffness weight (curvature).
        @param gamma        Edge attraction weight.
        @param iterations   Number of optimization iterations.
        @return Refined path snapped to edges. */
    std::vector<std::pair<double,double>> SnapToEdge(
        const std::vector<std::pair<double,double>>& initialPath,
        double alpha = 1.0,
        double beta = 1.0,
        double gamma = 1.0,
        int iterations = 50);

    //------------------------------------------------------------------------------------
    //  Simplification
    //------------------------------------------------------------------------------------

    /** Douglas-Peucker polyline simplification.
        Reduces point count while preserving shape within epsilon tolerance.
        @param points   Input polyline.
        @param epsilon  Maximum perpendicular distance tolerance.
        @return Simplified polyline. */
    static std::vector<std::pair<double,double>> DouglasPeucker(
        const std::vector<std::pair<double,double>>& points, double epsilon);

    /** Generate normal map from grayscale height map via Sobel gradient.
        Bright = high, dark = low.  Returns RGB buffer (caller must delete[]).
        Returns nullptr on failure.
        @param heightMap  Grayscale pixel buffer (1 byte per pixel).
        @param w          Image width in pixels.
        @param h          Image height in pixels.
        @param strength   Controls the steepness of perceived depth (default 2.0).
        @return RGB buffer of size w*h*3, or nullptr on failure. */
    static unsigned char* GenerateNormalFromHeight(const unsigned char* heightMap,
                                                    int w, int h, double strength = 2.0);

    /** Skeletonize a binary image using Zhang-Suen thinning.
        Input: grayscale image where dark pixels are foreground (< threshold).
        Output: binary image (0=bg, 255=skeleton) same dimensions as input.
        Caller must delete[] the result.
        @param grayscale  Input grayscale pixels (1 channel)
        @param w, h       Image dimensions
        @param threshold  Pixels darker than this are foreground (default 128)
        @return Skeletonized binary image, or nullptr on failure. */
    static unsigned char* Skeletonize(const unsigned char* grayscale,
                                       int w, int h, int threshold = 128);

    //------------------------------------------------------------------------------------
    //  Learning-integrated operations
    //------------------------------------------------------------------------------------

    /** Detect noise contours using LearningEngine's learned deletion patterns.
        For each contour, computes metrics and queries IsLikelyNoise.
        @param contours  Vector of contours to evaluate.
        @return Indices of contours that are likely noise. */
    std::vector<int> DetectNoise(const std::vector<Contour>& contours);

    /** A group of contours with a suggested name. */
    struct ContourGroup {
        std::vector<int> memberIndices;  // Indices into the input contour vector
        std::string suggestedName;       // e.g. "bolt_edges", "cylinder_rim"
        double confidence;               // 0-1 confidence in the grouping
    };

    /** Suggest contour groupings based on proximity, curvature, and learned affinity.
        Uses agglomerative clustering with multiple distance metrics.
        @param contours  Vector of contours to group.
        @return Suggested groupings. */
    std::vector<ContourGroup> SuggestGroups(const std::vector<Contour>& contours);

    //------------------------------------------------------------------------------------
    //  Vanishing point estimation
    //------------------------------------------------------------------------------------

    /** Estimated vanishing point from line clustering. */
    struct VanishingPointEstimate {
        double x = 0, y = 0;       // VP position in image pixel coordinates
        double confidence = 0;     // 0-1 based on cluster size relative to total lines
        int lineCount = 0;         // number of lines in this cluster
        double dominantAngle = 0;  // average theta of the line cluster (radians)
    };

    /** Estimate vanishing points from line convergence in the loaded image.
        Runs Canny + Hough, clusters lines by angle, intersects pairs within
        each cluster, and takes the median intersection point.
        @param maxVPs        Maximum number of VPs to return (default 2).
        @param cannyLow      Canny lower threshold.
        @param cannyHigh     Canny upper threshold.
        @param houghThreshold Minimum Hough accumulator votes.
        @return Vector of VPs sorted by confidence (largest cluster first). */
    std::vector<VanishingPointEstimate> EstimateVanishingPoints(
        int maxVPs = 2,
        double cannyLow = 50.0, double cannyHigh = 150.0,
        int houghThreshold = 30);

    //------------------------------------------------------------------------------------
    //  Surface type inference
    //------------------------------------------------------------------------------------

    /** Surface type classification matching Python SURFACE_TYPE_NAMES. */
    enum class SurfaceType : int {
        Unknown     = -1,
        Flat        = 0,
        Convex      = 1,
        Concave     = 2,
        Saddle      = 3,
        Cylindrical = 4
    };

    /** Result of surface type inference for a rectangular region. */
    struct SurfaceHint {
        SurfaceType type = SurfaceType::Unknown;
        double      confidence = 0.0;        // 0.0 - 1.0
        double      gradientAngle = 0.0;     // Dominant gradient direction (radians)
    };

    /** Mapping between Illustrator artwork coordinates and raster pixel coordinates. */
    struct ArtToPixelMapping {
        double artLeft = 0, artTop = 0, artRight = 0, artBottom = 0;
        int    pixelWidth = 0, pixelHeight = 0;
        bool   valid = false;

        /** Convert a rect in artwork coords to pixel rect. */
        void ArtRectToPixelRect(double aLeft, double aTop, double aRight, double aBottom,
                                int& pX, int& pY, int& pW, int& pH) const;
    };

    /** Infer the dominant surface type within a rectangular region of the loaded image.
        Uses gradient direction histogram analysis.
        @param x  Left edge of the region in pixel coordinates.
        @param y  Top edge of the region in pixel coordinates.
        @param w  Width of the region in pixels.
        @param h  Height of the region in pixels.
        @return SurfaceHint with type, confidence, and dominant gradient angle. */
    SurfaceHint InferSurfaceType(int x, int y, int w, int h);

    /** Result of k-means clustering on a DSINE normal map (RGB pixel data). */
    struct NormalRegion {
        double nx, ny, nz;           // cluster centroid normal direction (from RGB)
        int pixelCount;              // number of sampled pixels in this cluster
        double centerX, centerY;     // average pixel position of cluster members
        std::string label;           // auto-generated spatial label: "Top-Left", "Center", etc.
    };

    /** Cluster an RGB normal map into K surface regions via k-means on (R,G,B) vectors.
        Samples every Nth pixel for speed, treats RGB as normal direction.
        @param normalMapRGB  Raw RGB pixel data (3 bytes per pixel, row-major).
        @param width         Image width in pixels.
        @param height        Image height in pixels.
        @param k             Number of clusters.
        @param stride        Sample every Nth pixel (lower = more accurate, slower).
        @param maxIter       Maximum k-means iterations (higher = better convergence).
        @return Vector of NormalRegion sorted by pixel count (largest first). */
    std::vector<NormalRegion> ClusterNormalMapRegions(
        const unsigned char* normalMapRGB, int width, int height, int k,
        int stride = 4, int maxIter = 20);

    /** Result of normal direction clustering — a dominant surface plane. */
    struct PlaneCluster {
        double normalAngle = 0;    // Dominant gradient direction (radians, 0-pi)
        double strength = 0;       // Fraction of pixels in this cluster (0-1)
        int    pixelCount = 0;     // Number of pixels in cluster
    };

    /** Cluster gradient directions into dominant planes using k-means on angle histogram.
        Returns up to maxPlanes clusters sorted by strength (largest first).
        Each cluster represents a surface plane whose edges converge at a VP
        perpendicular to the cluster's dominant gradient angle.
        @param maxPlanes  Maximum number of plane clusters to return.
        @return Vector of PlaneCluster sorted by strength. */
    std::vector<PlaneCluster> ClusterNormalDirections(int maxPlanes = 3);

    /** Estimate vanishing points from normal direction clustering.
        Unlike Hough-based VP detection (which looks for line convergence),
        this derives VPs from surface plane orientations:
        - Cluster gradient directions into dominant planes
        - Each plane's edge direction is perpendicular to its gradient
        - Parallel edges from the same plane family converge at a VP
        @param maxVPs  Maximum number of VPs to return.
        @return Vector of VanishingPointEstimate derived from normal clusters. */
    std::vector<VanishingPointEstimate> EstimateVPsFromNormals(int maxVPs = 2);

    /** Set the artwork-to-pixel coordinate mapping.
        Called after loading an image and determining where it's placed on the artboard. */
    void SetArtToPixelMapping(double artLeft, double artTop, double artRight, double artBottom);

    /** Get the current mapping (returns by value for thread safety). */
    ArtToPixelMapping GetMapping() const { std::lock_guard<std::recursive_mutex> lock(mMutex); return artMapping; }

private:
    VisionEngine();
    ~VisionEngine();

    mutable std::recursive_mutex mMutex;  // P0: protects all mutable state (recursive for internal calls)

    ArtToPixelMapping artMapping;

    // Non-copyable
    VisionEngine(const VisionEngine&) = delete;
    VisionEngine& operator=(const VisionEngine&) = delete;

    //------------------------------------------------------------------------------------
    //  Image data (grayscale, read-only after loading)
    //------------------------------------------------------------------------------------

    std::vector<uint8_t> pixels;  // Grayscale pixel buffer
    int imgWidth  = 0;
    int imgHeight = 0;

    //------------------------------------------------------------------------------------
    //  Internal CV helpers
    //------------------------------------------------------------------------------------

    /** Apply Gaussian blur (separable 1D convolutions).
        @param src    Source grayscale image.
        @param w      Image width.
        @param h      Image height.
        @param sigma  Standard deviation of the Gaussian kernel.
        @return Blurred image. */
    static std::vector<uint8_t> GaussianBlur(const std::vector<uint8_t>& src,
                                              int w, int h, double sigma);

    /** Gradient computation result. */
    struct Gradient {
        std::vector<double> magnitude;  // Gradient magnitude per pixel
        std::vector<double> direction;  // Gradient direction per pixel (radians)
    };

    /** Compute image gradient via Sobel operators.
        @param blurred  Pre-blurred grayscale image.
        @param w        Image width.
        @param h        Image height.
        @return Gradient magnitude and direction. */
    static Gradient ComputeGradient(const std::vector<uint8_t>& blurred, int w, int h);

    /** Non-maximum suppression for Canny edge detection.
        Thins edges to single-pixel width.
        @param grad  Gradient data.
        @param w     Image width.
        @param h     Image height.
        @return Suppressed gradient magnitudes. */
    static std::vector<double> NonMaxSuppression(const Gradient& grad, int w, int h);

    /** Hysteresis thresholding for Canny edge detection.
        @param nms   Non-max suppressed gradient magnitudes.
        @param w     Image width.
        @param h     Image height.
        @param low   Lower threshold.
        @param high  Upper threshold.
        @return Binary edge map (0 or 255). */
    static std::vector<uint8_t> HysteresisThreshold(const std::vector<double>& nms,
                                                     int w, int h,
                                                     double low, double high);

    /** Trace a single contour using Moore boundary tracing algorithm.
        @param binary   Binary image.
        @param w        Image width.
        @param h        Image height.
        @param startX   Starting X coordinate.
        @param startY   Starting Y coordinate.
        @param visited  Visited pixel mask (updated in place).
        @return Traced contour. */
    Contour TraceContour(const std::vector<uint8_t>& binary, int w, int h,
                          int startX, int startY, std::vector<bool>& visited);

    //------------------------------------------------------------------------------------
    //  Contour metric helpers
    //------------------------------------------------------------------------------------

    /** Compute the mean curvature of a contour.
        Curvature at each point is the angle between adjacent segments. */
    static double MeanCurvature(const Contour& c);

    /** Compute the curvature variance of a contour. */
    static double CurvatureVariance(const Contour& c);

    /** Compute the centroid of a contour. */
    static std::pair<double,double> Centroid(const Contour& c);
};

//----------------------------------------------------------------------------------------
//  C-callable wrappers for HTTP bridge integration
//----------------------------------------------------------------------------------------

#ifdef __cplusplus
extern "C" {
#endif

/** Load an image into the vision engine.
    @param filePath  Absolute path to the image file.
    @return 1 on success, 0 on failure. */
int PluginVisionLoadImage(const char* filePath);

/** Check if an image is loaded in the vision engine.
    @return 1 if loaded, 0 if not. */
int PluginVisionIsLoaded();

/** Get the loaded image width. Returns 0 if no image loaded. */
int PluginVisionGetWidth();

/** Get the loaded image height. Returns 0 if no image loaded. */
int PluginVisionGetHeight();

#ifdef __cplusplus
}
#endif

#endif // __VISIONENGINE_H__
