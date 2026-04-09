//========================================================================================
//
//  IllTool Plugin -- Local Computer Vision Engine implementation
//
//  Pure C++ implementations of standard CV algorithms.
//  No OpenCV dependency -- all math is inline.
//
//  Performance targets: < 50ms for a 1000px image on all operations.
//
//========================================================================================

// stb_image implementation -- define once in the entire project
#define STB_IMAGE_IMPLEMENTATION
#include "vendor/stb_image.h"

#include "VisionEngine.h"
#include "LearningEngine.h"

#include <mutex>
#include <cstdio>
#include <cstring>
#include <cmath>
#include <algorithm>
#include <numeric>
#include <queue>
#include <stack>
#include <map>

//----------------------------------------------------------------------------------------
//  Logging prefix
//----------------------------------------------------------------------------------------

#define VE_LOG(fmt, ...) fprintf(stderr, "[IllTool Vision] " fmt "\n", ##__VA_ARGS__)

//========================================================================================
//  Singleton
//========================================================================================

VisionEngine& VisionEngine::Instance()
{
    static VisionEngine sInstance;
    return sInstance;
}

VisionEngine::VisionEngine()  {}
VisionEngine::~VisionEngine() {}

//========================================================================================
//  1. Image loading (via stb_image)
//========================================================================================

bool VisionEngine::LoadImage(const char* filePath)
{
    std::lock_guard<std::recursive_mutex> lock(mMutex);
    if (!filePath || filePath[0] == '\0') {
        VE_LOG("ERROR: LoadImage called with null/empty path");
        return false;
    }

    int w = 0, h = 0, channels = 0;

    // Load as grayscale (1 channel)
    unsigned char* data = stbi_load(filePath, &w, &h, &channels, 1);
    if (!data) {
        VE_LOG("ERROR: Failed to load image '%s': %s", filePath, stbi_failure_reason());
        return false;
    }

    // Copy into our buffer
    pixels.assign(data, data + (w * h));
    imgWidth  = w;
    imgHeight = h;
    stbi_image_free(data);

    VE_LOG("Loaded image: %s (%dx%d, original channels=%d)", filePath, w, h, channels);
    return true;
}

bool VisionEngine::IsLoaded() const
{
    std::lock_guard<std::recursive_mutex> lock(mMutex);
    return !pixels.empty() && imgWidth > 0 && imgHeight > 0;
}

int VisionEngine::Width() const  { std::lock_guard<std::recursive_mutex> lock(mMutex); return imgWidth; }
int VisionEngine::Height() const { std::lock_guard<std::recursive_mutex> lock(mMutex); return imgHeight; }

//========================================================================================
//  2. Gaussian blur (separable 1D convolutions)
//========================================================================================

std::vector<uint8_t> VisionEngine::GaussianBlur(const std::vector<uint8_t>& src,
                                                  int w, int h, double sigma)
{
    if (sigma <= 0.0) return src;

    // Compute kernel size: 3*sigma each side, rounded up to odd
    int kRadius = static_cast<int>(std::ceil(sigma * 3.0));
    if (kRadius < 1) kRadius = 1;
    int kSize = 2 * kRadius + 1;

    // Build 1D Gaussian kernel
    std::vector<double> kernel(kSize);
    double sum = 0.0;
    for (int i = 0; i < kSize; ++i) {
        double x = static_cast<double>(i - kRadius);
        kernel[i] = std::exp(-(x * x) / (2.0 * sigma * sigma));
        sum += kernel[i];
    }
    // Normalize
    for (int i = 0; i < kSize; ++i) {
        kernel[i] /= sum;
    }

    // Horizontal pass
    std::vector<double> temp(w * h, 0.0);
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            double val = 0.0;
            for (int k = -kRadius; k <= kRadius; ++k) {
                int sx = x + k;
                // Clamp to border
                if (sx < 0) sx = 0;
                if (sx >= w) sx = w - 1;
                val += static_cast<double>(src[y * w + sx]) * kernel[k + kRadius];
            }
            temp[y * w + x] = val;
        }
    }

    // Vertical pass
    std::vector<uint8_t> dst(w * h);
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            double val = 0.0;
            for (int k = -kRadius; k <= kRadius; ++k) {
                int sy = y + k;
                if (sy < 0) sy = 0;
                if (sy >= h) sy = h - 1;
                val += temp[sy * w + x] * kernel[k + kRadius];
            }
            int clamped = static_cast<int>(val + 0.5);
            if (clamped < 0)   clamped = 0;
            if (clamped > 255) clamped = 255;
            dst[y * w + x] = static_cast<uint8_t>(clamped);
        }
    }

    return dst;
}

//========================================================================================
//  3. Sobel gradient computation
//========================================================================================

VisionEngine::Gradient VisionEngine::ComputeGradient(const std::vector<uint8_t>& blurred,
                                                       int w, int h)
{
    Gradient grad;
    grad.magnitude.resize(w * h, 0.0);
    grad.direction.resize(w * h, 0.0);

    // Sobel kernels:
    //  Gx = [-1  0  1]    Gy = [-1 -2 -1]
    //       [-2  0  2]         [ 0  0  0]
    //       [-1  0  1]         [ 1  2  1]

    for (int y = 1; y < h - 1; ++y) {
        for (int x = 1; x < w - 1; ++x) {
            double p00 = blurred[(y-1)*w + (x-1)];
            double p01 = blurred[(y-1)*w + x    ];
            double p02 = blurred[(y-1)*w + (x+1)];
            double p10 = blurred[y    *w + (x-1)];
            // p11 = center, not used in Sobel
            double p12 = blurred[y    *w + (x+1)];
            double p20 = blurred[(y+1)*w + (x-1)];
            double p21 = blurred[(y+1)*w + x    ];
            double p22 = blurred[(y+1)*w + (x+1)];

            double gx = -p00 + p02 - 2.0*p10 + 2.0*p12 - p20 + p22;
            double gy = -p00 - 2.0*p01 - p02 + p20 + 2.0*p21 + p22;

            int idx = y * w + x;
            grad.magnitude[idx] = std::sqrt(gx * gx + gy * gy);
            grad.direction[idx] = std::atan2(gy, gx);
        }
    }

    return grad;
}

//========================================================================================
//  4. Canny edge detection
//========================================================================================

// 4a. Non-maximum suppression -- thin edges to single-pixel width
std::vector<double> VisionEngine::NonMaxSuppression(const Gradient& grad, int w, int h)
{
    std::vector<double> nms(w * h, 0.0);

    for (int y = 1; y < h - 1; ++y) {
        for (int x = 1; x < w - 1; ++x) {
            int idx = y * w + x;
            double mag = grad.magnitude[idx];
            double dir = grad.direction[idx];

            // Quantize direction to 0, 45, 90, 135 degrees
            // Convert to positive angle in [0, pi)
            double angle = dir;
            if (angle < 0) angle += M_PI;

            double q = 0.0, r = 0.0;

            // 0 degrees: compare East and West
            if ((angle >= 0 && angle < M_PI / 8.0) || (angle >= 7.0 * M_PI / 8.0)) {
                q = grad.magnitude[y * w + (x + 1)];
                r = grad.magnitude[y * w + (x - 1)];
            }
            // 45 degrees: compare NE and SW
            else if (angle >= M_PI / 8.0 && angle < 3.0 * M_PI / 8.0) {
                q = grad.magnitude[(y - 1) * w + (x + 1)];
                r = grad.magnitude[(y + 1) * w + (x - 1)];
            }
            // 90 degrees: compare North and South
            else if (angle >= 3.0 * M_PI / 8.0 && angle < 5.0 * M_PI / 8.0) {
                q = grad.magnitude[(y - 1) * w + x];
                r = grad.magnitude[(y + 1) * w + x];
            }
            // 135 degrees: compare NW and SE
            else {
                q = grad.magnitude[(y - 1) * w + (x - 1)];
                r = grad.magnitude[(y + 1) * w + (x + 1)];
            }

            // Keep pixel only if it's a local maximum along gradient direction
            if (mag >= q && mag >= r) {
                nms[idx] = mag;
            }
        }
    }

    return nms;
}

// 4b. Hysteresis thresholding -- connect weak edges to strong edges
std::vector<uint8_t> VisionEngine::HysteresisThreshold(const std::vector<double>& nms,
                                                         int w, int h,
                                                         double low, double high)
{
    std::vector<uint8_t> result(w * h, 0);

    const uint8_t STRONG = 255;
    const uint8_t WEAK   = 128;

    // First pass: classify pixels as strong, weak, or suppressed
    for (int i = 0; i < w * h; ++i) {
        if (nms[i] >= high) {
            result[i] = STRONG;
        } else if (nms[i] >= low) {
            result[i] = WEAK;
        }
    }

    // Second pass: connect weak edges to strong edges via BFS
    std::queue<int> queue;

    // Seed the queue with all strong pixels
    for (int i = 0; i < w * h; ++i) {
        if (result[i] == STRONG) {
            queue.push(i);
        }
    }

    // 8-connected neighbors
    const int dx[] = {-1, -1, -1, 0, 0, 1, 1, 1};
    const int dy[] = {-1,  0,  1,-1, 1,-1, 0, 1};

    while (!queue.empty()) {
        int idx = queue.front();
        queue.pop();

        int x = idx % w;
        int y = idx / w;

        for (int d = 0; d < 8; ++d) {
            int nx = x + dx[d];
            int ny = y + dy[d];
            if (nx >= 0 && nx < w && ny >= 0 && ny < h) {
                int nIdx = ny * w + nx;
                if (result[nIdx] == WEAK) {
                    result[nIdx] = STRONG;
                    queue.push(nIdx);
                }
            }
        }
    }

    // Final pass: keep only strong edges
    for (int i = 0; i < w * h; ++i) {
        result[i] = (result[i] == STRONG) ? 255 : 0;
    }

    return result;
}

// 4c. Full Canny pipeline
std::vector<uint8_t> VisionEngine::CannyEdges(double lowThresh, double highThresh)
{
    std::lock_guard<std::recursive_mutex> lock(mMutex);
    if (pixels.empty() || imgWidth <= 0 || imgHeight <= 0) {
        VE_LOG("ERROR: CannyEdges called with no image loaded");
        return {};
    }

    // Step 1: Gaussian blur (sigma = 1.4 is standard for Canny)
    auto blurred = GaussianBlur(pixels, imgWidth, imgHeight, 1.4);

    // Step 2: Compute gradient
    Gradient grad = ComputeGradient(blurred, imgWidth, imgHeight);

    // Step 3: Non-maximum suppression
    auto nms = NonMaxSuppression(grad, imgWidth, imgHeight);

    // Step 4: Hysteresis thresholding
    auto edges = HysteresisThreshold(nms, imgWidth, imgHeight, lowThresh, highThresh);

    VE_LOG("CannyEdges: %dx%d, thresh=[%.0f,%.0f]", imgWidth, imgHeight, lowThresh, highThresh);
    return edges;
}

// Sobel edges (simpler: just threshold the gradient magnitude)
std::vector<uint8_t> VisionEngine::SobelEdges(double threshold)
{
    std::lock_guard<std::recursive_mutex> lock(mMutex);
    if (pixels.empty() || imgWidth <= 0 || imgHeight <= 0) {
        VE_LOG("ERROR: SobelEdges called with no image loaded");
        return {};
    }

    auto blurred = GaussianBlur(pixels, imgWidth, imgHeight, 1.0);
    Gradient grad = ComputeGradient(blurred, imgWidth, imgHeight);

    std::vector<uint8_t> edges(imgWidth * imgHeight, 0);
    for (int i = 0; i < imgWidth * imgHeight; ++i) {
        edges[i] = (grad.magnitude[i] >= threshold) ? 255 : 0;
    }

    VE_LOG("SobelEdges: %dx%d, thresh=%.0f", imgWidth, imgHeight, threshold);
    return edges;
}

//========================================================================================
//  5. Contour extraction (Moore boundary tracing)
//========================================================================================

VisionEngine::Contour VisionEngine::TraceContour(const std::vector<uint8_t>& binary,
                                                    int w, int h,
                                                    int startX, int startY,
                                                    std::vector<bool>& visited)
{
    Contour contour;
    contour.area = 0.0;
    contour.arcLength = 0.0;
    contour.closed = false;

    // Moore neighborhood: 8 directions starting from right, going clockwise
    //  dir: 0=E, 1=SE, 2=S, 3=SW, 4=W, 5=NW, 6=N, 7=NE
    const int dx[] = { 1, 1, 0,-1,-1,-1, 0, 1};
    const int dy[] = { 0, 1, 1, 1, 0,-1,-1,-1};

    int cx = startX;
    int cy = startY;
    // Start searching from the West (direction 4) since we scan left-to-right
    int startDir = 4;

    contour.points.push_back({static_cast<double>(cx), static_cast<double>(cy)});
    visited[cy * w + cx] = true;

    int maxSteps = w * h;  // Safety limit
    int steps = 0;

    // Find the next boundary pixel by rotating clockwise from (startDir + 5) % 8
    // This is the Moore-Neighbor tracing algorithm
    int dir = (startDir + 5) % 8;

    while (steps < maxSteps) {
        bool found = false;

        for (int i = 0; i < 8; ++i) {
            int d = (dir + i) % 8;
            int nx = cx + dx[d];
            int ny = cy + dy[d];

            if (nx >= 0 && nx < w && ny >= 0 && ny < h && binary[ny * w + nx] != 0) {
                // Check if we've returned to start
                if (nx == startX && ny == startY && steps > 2) {
                    contour.closed = true;
                    found = true;
                    break;
                }

                cx = nx;
                cy = ny;
                contour.points.push_back({static_cast<double>(cx), static_cast<double>(cy)});
                visited[cy * w + cx] = true;

                // Next search starts from the opposite of current direction + 1
                dir = (d + 5) % 8;
                found = true;
                break;
            }
        }

        if (!found || contour.closed) break;
        ++steps;
    }

    // Compute arc length and area
    for (size_t i = 1; i < contour.points.size(); ++i) {
        double ddx = contour.points[i].first  - contour.points[i-1].first;
        double ddy = contour.points[i].second - contour.points[i-1].second;
        contour.arcLength += std::sqrt(ddx * ddx + ddy * ddy);
    }

    // Shoelace formula for area (meaningful for closed contours)
    if (contour.closed && contour.points.size() >= 3) {
        double a = 0.0;
        size_t n = contour.points.size();
        for (size_t i = 0; i < n; ++i) {
            size_t j = (i + 1) % n;
            a += contour.points[i].first * contour.points[j].second;
            a -= contour.points[j].first * contour.points[i].second;
        }
        contour.area = std::abs(a) / 2.0;
    }

    return contour;
}

std::vector<VisionEngine::Contour> VisionEngine::FindContours(
    const std::vector<uint8_t>& binary, int w, int h, int minLength)
{
    std::lock_guard<std::recursive_mutex> lock(mMutex);
    std::vector<Contour> contours;
    std::vector<bool> visited(w * h, false);

    // Scan for boundary pixels (foreground pixel with at least one background neighbor)
    for (int y = 1; y < h - 1; ++y) {
        for (int x = 1; x < w - 1; ++x) {
            if (binary[y * w + x] == 0) continue;
            if (visited[y * w + x]) continue;

            // Check if this is a boundary pixel (has at least one background 4-neighbor)
            bool isBoundary = false;
            if (binary[(y-1)*w + x] == 0 || binary[(y+1)*w + x] == 0 ||
                binary[y*w + (x-1)] == 0 || binary[y*w + (x+1)] == 0) {
                isBoundary = true;
            }

            if (!isBoundary) {
                visited[y * w + x] = true;
                continue;
            }

            Contour c = TraceContour(binary, w, h, x, y, visited);
            if (static_cast<int>(c.points.size()) >= minLength) {
                contours.push_back(std::move(c));
            }
        }
    }

    VE_LOG("FindContours: found %d contours (minLength=%d)", (int)contours.size(), minLength);
    return contours;
}

//========================================================================================
//  6. Douglas-Peucker simplification
//========================================================================================

std::vector<std::pair<double,double>> VisionEngine::DouglasPeucker(
    const std::vector<std::pair<double,double>>& points, double epsilon)
{
    if (points.size() < 3) return points;

    // Find point with maximum distance from line between first and last
    double dmax = 0.0;
    size_t imax = 0;

    auto first = points.front();
    auto last  = points.back();

    // Line direction
    double lx = last.first  - first.first;
    double ly = last.second - first.second;
    double lineLen = std::sqrt(lx * lx + ly * ly);

    for (size_t i = 1; i < points.size() - 1; ++i) {
        double d;
        if (lineLen < 1e-10) {
            // Degenerate: first and last are the same point
            double ddx = points[i].first  - first.first;
            double ddy = points[i].second - first.second;
            d = std::sqrt(ddx * ddx + ddy * ddy);
        } else {
            // Perpendicular distance from point to line
            double dx = points[i].first  - first.first;
            double dy = points[i].second - first.second;
            d = std::abs(dx * ly - dy * lx) / lineLen;
        }

        if (d > dmax) {
            dmax = d;
            imax = i;
        }
    }

    // If max distance exceeds epsilon, recursively simplify
    if (dmax > epsilon) {
        std::vector<std::pair<double,double>> left(points.begin(), points.begin() + imax + 1);
        std::vector<std::pair<double,double>> right(points.begin() + imax, points.end());

        auto rLeft  = DouglasPeucker(left, epsilon);
        auto rRight = DouglasPeucker(right, epsilon);

        // Merge (skip duplicate junction point)
        std::vector<std::pair<double,double>> result;
        result.insert(result.end(), rLeft.begin(), rLeft.end() - 1);
        result.insert(result.end(), rRight.begin(), rRight.end());
        return result;
    } else {
        // Keep only endpoints
        return {first, last};
    }
}

//========================================================================================
//  7. Multi-scale edges
//========================================================================================

std::vector<uint8_t> VisionEngine::MultiScaleEdges(int numScales, double voteThreshold)
{
    std::lock_guard<std::recursive_mutex> lock(mMutex);
    if (pixels.empty() || imgWidth <= 0 || imgHeight <= 0) {
        VE_LOG("ERROR: MultiScaleEdges called with no image loaded");
        return {};
    }

    int totalPixels = imgWidth * imgHeight;
    std::vector<int> votes(totalPixels, 0);

    // Run Canny at multiple threshold scales
    // Low threshold ranges from 20 to 100, high from 60 to 200
    for (int s = 0; s < numScales; ++s) {
        double t = static_cast<double>(s) / std::max(1, numScales - 1);
        double low  = 20.0  + t * 80.0;
        double high = 60.0  + t * 140.0;

        auto edges = CannyEdges(low, high);
        for (int i = 0; i < totalPixels; ++i) {
            if (edges[i] != 0) {
                votes[i]++;
            }
        }
    }

    // Threshold: keep pixels that appear in enough scales
    std::vector<uint8_t> result(totalPixels, 0);
    int kept = 0;
    for (int i = 0; i < totalPixels; ++i) {
        if (static_cast<double>(votes[i]) >= voteThreshold) {
            result[i] = 255;
            ++kept;
        }
    }

    VE_LOG("MultiScaleEdges: %d scales, voteThresh=%.0f, %d edge pixels kept",
           numScales, voteThreshold, kept);
    return result;
}

//========================================================================================
//  8. Flood fill (queue-based BFS)
//========================================================================================

std::vector<uint8_t> VisionEngine::FloodFillMask(int seedX, int seedY, int tolerance)
{
    std::lock_guard<std::recursive_mutex> lock(mMutex);
    if (pixels.empty() || imgWidth <= 0 || imgHeight <= 0) {
        VE_LOG("ERROR: FloodFillMask called with no image loaded");
        return {};
    }

    int w = imgWidth;
    int h = imgHeight;

    if (seedX < 0 || seedX >= w || seedY < 0 || seedY >= h) {
        VE_LOG("ERROR: FloodFillMask seed (%d,%d) out of bounds", seedX, seedY);
        return {};
    }

    std::vector<uint8_t> mask(w * h, 0);
    uint8_t seedVal = pixels[seedY * w + seedX];

    std::queue<std::pair<int,int>> queue;
    queue.push({seedX, seedY});
    mask[seedY * w + seedX] = 255;

    const int dx[] = {-1, 1, 0, 0};
    const int dy[] = { 0, 0,-1, 1};

    int filled = 0;
    while (!queue.empty()) {
        auto [cx, cy] = queue.front();
        queue.pop();
        ++filled;

        for (int d = 0; d < 4; ++d) {
            int nx = cx + dx[d];
            int ny = cy + dy[d];
            if (nx < 0 || nx >= w || ny < 0 || ny >= h) continue;
            int nIdx = ny * w + nx;
            if (mask[nIdx] != 0) continue;

            int diff = static_cast<int>(pixels[nIdx]) - static_cast<int>(seedVal);
            if (diff < 0) diff = -diff;
            if (diff <= tolerance) {
                mask[nIdx] = 255;
                queue.push({nx, ny});
            }
        }
    }

    VE_LOG("FloodFillMask: seed=(%d,%d), tolerance=%d, filled %d pixels",
           seedX, seedY, tolerance, filled);
    return mask;
}

//========================================================================================
//  9. Connected components (union-find)
//========================================================================================

namespace {

// Disjoint set (union-find) for connected component labeling
class DisjointSet {
public:
    explicit DisjointSet(int n) : parent(n), rank(n, 0) {
        std::iota(parent.begin(), parent.end(), 0);
    }

    int Find(int x) {
        while (parent[x] != x) {
            parent[x] = parent[parent[x]];  // Path compression
            x = parent[x];
        }
        return x;
    }

    void Union(int a, int b) {
        a = Find(a);
        b = Find(b);
        if (a == b) return;
        if (rank[a] < rank[b]) std::swap(a, b);
        parent[b] = a;
        if (rank[a] == rank[b]) rank[a]++;
    }

private:
    std::vector<int> parent;
    std::vector<int> rank;
};

} // anonymous namespace

std::vector<std::vector<std::pair<int,int>>> VisionEngine::ConnectedComponents(
    const std::vector<uint8_t>& binary, int w, int h)
{
    std::lock_guard<std::recursive_mutex> lock(mMutex);
    int n = w * h;
    DisjointSet ds(n);

    // First pass: union neighboring foreground pixels
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            if (binary[y * w + x] == 0) continue;

            int idx = y * w + x;

            // Check 4-connected neighbors already visited (left, above)
            if (x > 0 && binary[y * w + (x - 1)] != 0) {
                ds.Union(idx, y * w + (x - 1));
            }
            if (y > 0 && binary[(y - 1) * w + x] != 0) {
                ds.Union(idx, (y - 1) * w + x);
            }
        }
    }

    // Second pass: collect components
    std::map<int, std::vector<std::pair<int,int>>> componentMap;
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            if (binary[y * w + x] == 0) continue;
            int label = ds.Find(y * w + x);
            componentMap[label].push_back({x, y});
        }
    }

    std::vector<std::vector<std::pair<int,int>>> components;
    components.reserve(componentMap.size());
    for (auto& [label, pixels] : componentMap) {
        components.push_back(std::move(pixels));
    }

    VE_LOG("ConnectedComponents: %d components in %dx%d image", (int)components.size(), w, h);
    return components;
}

//========================================================================================
//  10. Hough line detection
//========================================================================================

std::vector<VisionEngine::HoughLine> VisionEngine::DetectLines(
    const std::vector<uint8_t>& edges,
    double rhoRes, double thetaRes, int threshold)
{
    std::lock_guard<std::recursive_mutex> lock(mMutex);
    if (edges.empty()) return {};

    int w = imgWidth;
    int h = imgHeight;

    // Diagonal length = maximum possible rho
    double diagLen = std::sqrt(static_cast<double>(w * w + h * h));
    int numRho   = static_cast<int>(std::ceil(2.0 * diagLen / rhoRes));
    int numTheta = static_cast<int>(std::ceil(M_PI / thetaRes));

    // Accumulator array
    std::vector<int> accum(numRho * numTheta, 0);

    // Precompute sin/cos tables
    std::vector<double> cosTable(numTheta), sinTable(numTheta);
    for (int t = 0; t < numTheta; ++t) {
        double theta = static_cast<double>(t) * thetaRes;
        cosTable[t] = std::cos(theta);
        sinTable[t] = std::sin(theta);
    }

    // Vote
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            if (edges[y * w + x] == 0) continue;

            for (int t = 0; t < numTheta; ++t) {
                double rho = static_cast<double>(x) * cosTable[t] +
                             static_cast<double>(y) * sinTable[t];
                int rIdx = static_cast<int>(std::round((rho + diagLen) / rhoRes));
                if (rIdx >= 0 && rIdx < numRho) {
                    accum[rIdx * numTheta + t]++;
                }
            }
        }
    }

    // Extract peaks above threshold
    std::vector<HoughLine> lines;
    for (int r = 0; r < numRho; ++r) {
        for (int t = 0; t < numTheta; ++t) {
            int votes = accum[r * numTheta + t];
            if (votes >= threshold) {
                HoughLine line;
                line.rho   = static_cast<double>(r) * rhoRes - diagLen;
                line.theta = static_cast<double>(t) * thetaRes;
                line.votes = votes;
                lines.push_back(line);
            }
        }
    }

    // Sort by vote count descending
    std::sort(lines.begin(), lines.end(),
              [](const HoughLine& a, const HoughLine& b) { return a.votes > b.votes; });

    VE_LOG("DetectLines: %d lines above threshold %d", (int)lines.size(), threshold);
    return lines;
}

//========================================================================================
//  11. Hough circle detection
//========================================================================================

std::vector<VisionEngine::Circle> VisionEngine::DetectCircles(
    const std::vector<uint8_t>& edges,
    double minRadius, double maxRadius, int threshold)
{
    std::lock_guard<std::recursive_mutex> lock(mMutex);
    if (edges.empty()) return {};

    int w = imgWidth;
    int h = imgHeight;

    // We need the gradient direction from the original image
    auto blurred = GaussianBlur(pixels, w, h, 1.4);
    Gradient grad = ComputeGradient(blurred, w, h);

    // Discretize radius range
    int numR = static_cast<int>(maxRadius - minRadius) + 1;
    if (numR <= 0) return {};

    // 3D accumulator: (cx, cy, radius)
    // To keep memory reasonable, downsample if image is large
    int scale = 1;
    int aw = w / scale;
    int ah = h / scale;
    std::vector<int> accum(aw * ah * numR, 0);

    // For each edge pixel, vote along the gradient direction for possible centers
    for (int y = 1; y < h - 1; ++y) {
        for (int x = 1; x < w - 1; ++x) {
            if (edges[y * w + x] == 0) continue;

            double dir = grad.direction[y * w + x];
            double cosD = std::cos(dir);
            double sinD = std::sin(dir);

            for (int ri = 0; ri < numR; ++ri) {
                double r = minRadius + static_cast<double>(ri);

                // Vote in both directions along gradient
                for (int sign = -1; sign <= 1; sign += 2) {
                    int cx = static_cast<int>(std::round(x + sign * r * cosD)) / scale;
                    int cy = static_cast<int>(std::round(y + sign * r * sinD)) / scale;

                    if (cx >= 0 && cx < aw && cy >= 0 && cy < ah) {
                        accum[(cy * aw + cx) * numR + ri]++;
                    }
                }
            }
        }
    }

    // Extract peaks
    std::vector<Circle> circles;
    for (int cy = 0; cy < ah; ++cy) {
        for (int cx = 0; cx < aw; ++cx) {
            for (int ri = 0; ri < numR; ++ri) {
                int votes = accum[(cy * aw + cx) * numR + ri];
                if (votes >= threshold) {
                    Circle c;
                    c.cx     = static_cast<double>(cx * scale);
                    c.cy     = static_cast<double>(cy * scale);
                    c.radius = minRadius + static_cast<double>(ri);
                    c.votes  = votes;
                    circles.push_back(c);
                }
            }
        }
    }

    // Sort by vote count descending
    std::sort(circles.begin(), circles.end(),
              [](const Circle& a, const Circle& b) { return a.votes > b.votes; });

    // Simple non-maximum suppression: remove circles too close to a stronger one
    std::vector<Circle> filtered;
    for (const auto& c : circles) {
        bool suppressed = false;
        for (const auto& f : filtered) {
            double dx = c.cx - f.cx;
            double dy = c.cy - f.cy;
            double dist = std::sqrt(dx * dx + dy * dy);
            double rDiff = std::abs(c.radius - f.radius);
            if (dist < f.radius * 0.5 && rDiff < f.radius * 0.3) {
                suppressed = true;
                break;
            }
        }
        if (!suppressed) {
            filtered.push_back(c);
        }
    }

    VE_LOG("DetectCircles: %d circles (before NMS: %d), r=[%.0f,%.0f]",
           (int)filtered.size(), (int)circles.size(), minRadius, maxRadius);
    return filtered;
}

//========================================================================================
//  12. Active contours (snake) -- energy minimization via gradient descent
//========================================================================================

std::vector<std::pair<double,double>> VisionEngine::SnapToEdge(
    const std::vector<std::pair<double,double>>& initialPath,
    double alpha, double beta, double gamma, int iterations)
{
    std::lock_guard<std::recursive_mutex> lock(mMutex);
    if (initialPath.size() < 3 || pixels.empty() || imgWidth <= 0 || imgHeight <= 0) {
        return initialPath;
    }

    int w = imgWidth;
    int h = imgHeight;

    // Precompute edge energy map: gradient magnitude of the image
    auto blurred = GaussianBlur(pixels, w, h, 1.0);
    Gradient grad = ComputeGradient(blurred, w, h);

    // Normalize gradient magnitude to [0,1]
    double maxMag = 0.0;
    for (const auto& m : grad.magnitude) {
        if (m > maxMag) maxMag = m;
    }
    std::vector<double> edgeEnergy(w * h, 0.0);
    if (maxMag > 0.0) {
        for (int i = 0; i < w * h; ++i) {
            edgeEnergy[i] = grad.magnitude[i] / maxMag;
        }
    }

    // Precompute gradient of edge energy (external force field)
    // Use central differences on the edge energy map
    std::vector<double> fx(w * h, 0.0);
    std::vector<double> fy(w * h, 0.0);
    for (int y = 1; y < h - 1; ++y) {
        for (int x = 1; x < w - 1; ++x) {
            int idx = y * w + x;
            fx[idx] = (edgeEnergy[y * w + (x + 1)] - edgeEnergy[y * w + (x - 1)]) * 0.5;
            fy[idx] = (edgeEnergy[(y + 1) * w + x] - edgeEnergy[(y - 1) * w + x]) * 0.5;
        }
    }

    // Initialize snake points
    std::vector<std::pair<double,double>> snake = initialPath;
    int n = static_cast<int>(snake.size());

    // Iterative gradient descent
    double step = 1.0;  // Step size

    for (int iter = 0; iter < iterations; ++iter) {
        std::vector<std::pair<double,double>> newSnake(n);

        for (int i = 0; i < n; ++i) {
            int prev = (i - 1 + n) % n;
            int next = (i + 1) % n;

            // Internal energy: elasticity (first derivative)
            double elastX = alpha * (snake[prev].first + snake[next].first - 2.0 * snake[i].first);
            double elastY = alpha * (snake[prev].second + snake[next].second - 2.0 * snake[i].second);

            // Internal energy: stiffness (second derivative)
            int prev2 = (i - 2 + n) % n;
            int next2 = (i + 2) % n;
            double stiffX = beta * (snake[prev2].first - 4.0 * snake[prev].first +
                                     6.0 * snake[i].first - 4.0 * snake[next].first +
                                     snake[next2].first);
            double stiffY = beta * (snake[prev2].second - 4.0 * snake[prev].second +
                                     6.0 * snake[i].second - 4.0 * snake[next].second +
                                     snake[next2].second);

            // External energy: edge attraction
            int px = static_cast<int>(std::round(snake[i].first));
            int py = static_cast<int>(std::round(snake[i].second));
            double extX = 0.0, extY = 0.0;
            if (px >= 0 && px < w && py >= 0 && py < h) {
                int idx = py * w + px;
                extX = gamma * fx[idx];
                extY = gamma * fy[idx];
            }

            // Update position
            newSnake[i].first  = snake[i].first  + step * (elastX - stiffX + extX);
            newSnake[i].second = snake[i].second + step * (elastY - stiffY + extY);

            // Clamp to image bounds
            if (newSnake[i].first  < 0) newSnake[i].first  = 0;
            if (newSnake[i].first  >= w) newSnake[i].first = w - 1;
            if (newSnake[i].second < 0) newSnake[i].second = 0;
            if (newSnake[i].second >= h) newSnake[i].second = h - 1;
        }

        snake = newSnake;
    }

    VE_LOG("SnapToEdge: %d points, %d iterations", n, iterations);
    return snake;
}

//========================================================================================
//  13. DetectNoise -- learning-integrated noise detection
//========================================================================================

double VisionEngine::MeanCurvature(const Contour& c)
{
    if (c.points.size() < 3) return 0.0;

    double totalCurv = 0.0;
    int count = 0;

    for (size_t i = 1; i < c.points.size() - 1; ++i) {
        double ax = c.points[i].first   - c.points[i-1].first;
        double ay = c.points[i].second  - c.points[i-1].second;
        double bx = c.points[i+1].first - c.points[i].first;
        double by = c.points[i+1].second - c.points[i].second;

        double lenA = std::sqrt(ax * ax + ay * ay);
        double lenB = std::sqrt(bx * bx + by * by);
        if (lenA < 1e-10 || lenB < 1e-10) continue;

        // Cross product gives sin(angle), dot gives cos(angle)
        double cross = ax * by - ay * bx;
        double dot   = ax * bx + ay * by;
        double angle = std::atan2(cross, dot);
        totalCurv += std::abs(angle);
        ++count;
    }

    return (count > 0) ? totalCurv / count : 0.0;
}

double VisionEngine::CurvatureVariance(const Contour& c)
{
    if (c.points.size() < 3) return 0.0;

    std::vector<double> curvatures;
    for (size_t i = 1; i < c.points.size() - 1; ++i) {
        double ax = c.points[i].first   - c.points[i-1].first;
        double ay = c.points[i].second  - c.points[i-1].second;
        double bx = c.points[i+1].first - c.points[i].first;
        double by = c.points[i+1].second - c.points[i].second;

        double lenA = std::sqrt(ax * ax + ay * ay);
        double lenB = std::sqrt(bx * bx + by * by);
        if (lenA < 1e-10 || lenB < 1e-10) continue;

        double cross = ax * by - ay * bx;
        double dot   = ax * bx + ay * by;
        double angle = std::atan2(cross, dot);
        curvatures.push_back(std::abs(angle));
    }

    if (curvatures.empty()) return 0.0;

    double mean = 0.0;
    for (double k : curvatures) mean += k;
    mean /= curvatures.size();

    double variance = 0.0;
    for (double k : curvatures) {
        double diff = k - mean;
        variance += diff * diff;
    }
    variance /= curvatures.size();

    return variance;
}

std::pair<double,double> VisionEngine::Centroid(const Contour& c)
{
    if (c.points.empty()) return {0.0, 0.0};

    double sx = 0.0, sy = 0.0;
    for (const auto& p : c.points) {
        sx += p.first;
        sy += p.second;
    }
    return {sx / c.points.size(), sy / c.points.size()};
}

std::vector<int> VisionEngine::DetectNoise(const std::vector<Contour>& contours)
{
    std::lock_guard<std::recursive_mutex> lock(mMutex);
    std::vector<int> noiseIndices;

    LearningEngine& le = LearningEngine::Instance();
    if (!le.IsOpen()) {
        VE_LOG("DetectNoise: LearningEngine not open, skipping");
        return noiseIndices;
    }

    for (size_t i = 0; i < contours.size(); ++i) {
        const Contour& c = contours[i];
        double arcLen  = c.arcLength;
        int pointCount = static_cast<int>(c.points.size());
        double curvVar = CurvatureVariance(c);

        if (le.IsLikelyNoise(arcLen, pointCount, curvVar)) {
            noiseIndices.push_back(static_cast<int>(i));
        }
    }

    VE_LOG("DetectNoise: %d/%d contours flagged as noise",
           (int)noiseIndices.size(), (int)contours.size());
    return noiseIndices;
}

//========================================================================================
//  14. SuggestGroups -- learning-integrated contour grouping
//========================================================================================

std::vector<VisionEngine::ContourGroup> VisionEngine::SuggestGroups(
    const std::vector<Contour>& contours)
{
    std::lock_guard<std::recursive_mutex> lock(mMutex);
    int n = static_cast<int>(contours.size());
    if (n < 2) return {};

    // Compute per-contour metrics
    struct Metrics {
        std::pair<double,double> centroid;
        double meanCurv;
        double arcLength;
    };

    std::vector<Metrics> metrics(n);
    for (int i = 0; i < n; ++i) {
        metrics[i].centroid   = Centroid(contours[i]);
        metrics[i].meanCurv   = MeanCurvature(contours[i]);
        metrics[i].arcLength  = contours[i].arcLength;
    }

    // Compute pairwise distance matrix (combined metric)
    // Distance = weighted combination of spatial distance + curvature dissimilarity
    std::vector<double> distMatrix(n * n, 0.0);

    // Find max spatial distance for normalization
    double maxDist = 0.0;
    for (int i = 0; i < n; ++i) {
        for (int j = i + 1; j < n; ++j) {
            double dx = metrics[i].centroid.first  - metrics[j].centroid.first;
            double dy = metrics[i].centroid.second - metrics[j].centroid.second;
            double d = std::sqrt(dx * dx + dy * dy);
            if (d > maxDist) maxDist = d;
        }
    }
    if (maxDist < 1e-10) maxDist = 1.0;

    for (int i = 0; i < n; ++i) {
        for (int j = i + 1; j < n; ++j) {
            // Spatial distance (normalized)
            double dx = metrics[i].centroid.first  - metrics[j].centroid.first;
            double dy = metrics[i].centroid.second - metrics[j].centroid.second;
            double spatialDist = std::sqrt(dx * dx + dy * dy) / maxDist;

            // Curvature similarity: ratio of mean curvatures (1.0 = identical)
            double c1 = metrics[i].meanCurv;
            double c2 = metrics[j].meanCurv;
            double curvSim = 1.0;
            if (c1 > 1e-10 && c2 > 1e-10) {
                curvSim = std::min(c1, c2) / std::max(c1, c2);
            }
            double curvDist = 1.0 - curvSim;

            // Arc length similarity
            double a1 = metrics[i].arcLength;
            double a2 = metrics[j].arcLength;
            double lenSim = 1.0;
            if (a1 > 1e-10 && a2 > 1e-10) {
                lenSim = std::min(a1, a2) / std::max(a1, a2);
            }
            double lenDist = 1.0 - lenSim;

            // Combined distance: weighted sum
            double combined = 0.5 * spatialDist + 0.3 * curvDist + 0.2 * lenDist;
            distMatrix[i * n + j] = combined;
            distMatrix[j * n + i] = combined;
        }
    }

    // Agglomerative clustering (single-linkage)
    // Start with each contour in its own cluster
    std::vector<int> clusterLabel(n);
    std::iota(clusterLabel.begin(), clusterLabel.end(), 0);

    double mergeThreshold = 0.35;  // Empirical threshold for merging

    bool merged = true;
    while (merged) {
        merged = false;

        // Find closest pair of different clusters
        double minDist = 1e30;
        int mergeA = -1, mergeB = -1;

        for (int i = 0; i < n; ++i) {
            for (int j = i + 1; j < n; ++j) {
                if (clusterLabel[i] == clusterLabel[j]) continue;
                if (distMatrix[i * n + j] < minDist) {
                    minDist = distMatrix[i * n + j];
                    mergeA = i;
                    mergeB = j;
                }
            }
        }

        if (mergeA >= 0 && minDist < mergeThreshold) {
            int labelA = clusterLabel[mergeA];
            int labelB = clusterLabel[mergeB];
            // Merge B's cluster into A's
            for (int i = 0; i < n; ++i) {
                if (clusterLabel[i] == labelB) {
                    clusterLabel[i] = labelA;
                }
            }
            merged = true;
        }
    }

    // Collect groups
    std::map<int, std::vector<int>> groupMap;
    for (int i = 0; i < n; ++i) {
        groupMap[clusterLabel[i]].push_back(i);
    }

    std::vector<ContourGroup> groups;
    for (auto& [label, members] : groupMap) {
        if (members.size() < 2) continue;  // Skip singletons

        ContourGroup grp;
        grp.memberIndices = members;

        // Compute average metrics for naming
        double avgCurv = 0.0;
        double avgLen  = 0.0;
        for (int idx : members) {
            avgCurv += metrics[idx].meanCurv;
            avgLen  += metrics[idx].arcLength;
        }
        avgCurv /= members.size();
        avgLen  /= members.size();

        // Name based on dominant characteristics
        if (avgCurv < 0.1 && avgLen > 50.0) {
            grp.suggestedName = "straight_edges";
        } else if (avgCurv < 0.1 && avgLen <= 50.0) {
            grp.suggestedName = "short_straight";
        } else if (avgCurv > 0.5 && avgLen > 100.0) {
            grp.suggestedName = "large_arc";
        } else if (avgCurv > 0.5 && avgLen <= 100.0) {
            grp.suggestedName = "small_curve";
        } else if (avgCurv > 0.3) {
            grp.suggestedName = "curved_edges";
        } else {
            grp.suggestedName = "mixed_edges";
        }

        // Confidence based on cluster tightness
        double avgDist = 0.0;
        int pairCount = 0;
        for (size_t a = 0; a < members.size(); ++a) {
            for (size_t b = a + 1; b < members.size(); ++b) {
                avgDist += distMatrix[members[a] * n + members[b]];
                ++pairCount;
            }
        }
        if (pairCount > 0) avgDist /= pairCount;
        grp.confidence = std::max(0.0, 1.0 - avgDist / mergeThreshold);

        groups.push_back(std::move(grp));
    }

    VE_LOG("SuggestGroups: %d groups from %d contours", (int)groups.size(), n);
    return groups;
}

//========================================================================================
//  Vanishing point estimation
//========================================================================================

std::vector<VisionEngine::VanishingPointEstimate> VisionEngine::EstimateVanishingPoints(
    int maxVPs, double cannyLow, double cannyHigh, int houghThreshold)
{
    std::lock_guard<std::recursive_mutex> lock(mMutex);
    std::vector<VanishingPointEstimate> results;

    if (!IsLoaded()) {
        VE_LOG("EstimateVanishingPoints: no image loaded");
        return results;
    }

    VE_LOG("EstimateVanishingPoints: image %dx%d, maxVPs=%d, canny=[%.0f,%.0f], hough=%d",
           imgWidth, imgHeight, maxVPs, cannyLow, cannyHigh, houghThreshold);

    // Step 1: Edge detection
    auto edges = CannyEdges(cannyLow, cannyHigh);
    if (edges.empty()) {
        VE_LOG("EstimateVanishingPoints: edge detection returned empty");
        return results;
    }

    // Step 2: Hough line detection
    auto lines = DetectLines(edges, 1.0, M_PI / 180.0, houghThreshold);
    VE_LOG("EstimateVanishingPoints: %d raw lines detected", (int)lines.size());
    if (lines.size() < 2) {
        VE_LOG("EstimateVanishingPoints: not enough lines for VP estimation");
        return results;
    }

    // Cap lines to top 200 by vote count (already sorted descending)
    if (lines.size() > 200) lines.resize(200);

    // Step 3: Filter near-horizontal (theta near 0 or pi) and near-vertical (theta near pi/2)
    // In Hough space theta is in [0, pi). Horizontal lines have theta near pi/2,
    // vertical lines have theta near 0 or pi.
    const double kFilterDeg = 5.0;
    const double kFilterRad = kFilterDeg * M_PI / 180.0;
    std::vector<HoughLine> perspLines;
    for (auto& l : lines) {
        double theta = l.theta;
        // Near-vertical: theta close to 0 or close to pi
        if (theta < kFilterRad || theta > (M_PI - kFilterRad)) continue;
        // Near-horizontal: theta close to pi/2
        if (std::abs(theta - M_PI / 2.0) < kFilterRad) continue;
        perspLines.push_back(l);
    }
    VE_LOG("EstimateVanishingPoints: %d lines after filtering horiz/vert", (int)perspLines.size());
    if (perspLines.size() < 2) {
        VE_LOG("EstimateVanishingPoints: not enough perspective lines after filtering");
        return results;
    }

    // Step 4: Cluster by theta angle using 10-degree bins
    const double kBinWidth = 10.0 * M_PI / 180.0;  // 10 degrees in radians
    const int kNumBins = static_cast<int>(std::ceil(M_PI / kBinWidth));
    std::vector<std::vector<int>> bins(kNumBins);
    for (int i = 0; i < (int)perspLines.size(); i++) {
        int bin = static_cast<int>(perspLines[i].theta / kBinWidth);
        if (bin >= kNumBins) bin = kNumBins - 1;
        bins[bin].push_back(i);
    }

    // Step 5: Find the largest clusters (merge adjacent bins for robustness)
    // Build cluster list: each cluster is a set of line indices
    struct Cluster {
        std::vector<int> lineIndices;
        double avgTheta;
        int totalVotes;
    };
    std::vector<Cluster> clusters;

    // Merge adjacent non-empty bins into clusters
    for (int b = 0; b < kNumBins; b++) {
        if (bins[b].empty()) continue;

        Cluster c;
        c.lineIndices = bins[b];
        c.totalVotes = 0;
        c.avgTheta = 0;

        // Merge with next bin if also non-empty (handles lines on bin boundaries)
        if (b + 1 < kNumBins && !bins[b + 1].empty()) {
            c.lineIndices.insert(c.lineIndices.end(), bins[b + 1].begin(), bins[b + 1].end());
            b++;  // skip the merged bin
        }

        // Compute weighted average theta and total votes
        double sumTheta = 0;
        for (int idx : c.lineIndices) {
            sumTheta += perspLines[idx].theta * perspLines[idx].votes;
            c.totalVotes += perspLines[idx].votes;
        }
        c.avgTheta = (c.totalVotes > 0) ? sumTheta / c.totalVotes : 0;
        clusters.push_back(std::move(c));
    }

    // Sort clusters by total votes (proxy for size/importance)
    std::sort(clusters.begin(), clusters.end(),
              [](const Cluster& a, const Cluster& b) { return a.totalVotes > b.totalVotes; });

    VE_LOG("EstimateVanishingPoints: %d angle clusters formed", (int)clusters.size());

    // Step 6: For each of the top clusters, compute VP by median intersection
    int vpCount = std::min(maxVPs, (int)clusters.size());
    for (int ci = 0; ci < vpCount; ci++) {
        const Cluster& cluster = clusters[ci];
        if ((int)cluster.lineIndices.size() < 2) continue;

        // Intersect all pairs of lines in this cluster
        std::vector<double> xs, ys;
        int nLines = (int)cluster.lineIndices.size();
        // Limit pairs to avoid O(n^2) explosion
        int maxPairs = 500;
        int pairCount = 0;
        for (int a = 0; a < nLines && pairCount < maxPairs; a++) {
            for (int b = a + 1; b < nLines && pairCount < maxPairs; b++) {
                const HoughLine& l1 = perspLines[cluster.lineIndices[a]];
                const HoughLine& l2 = perspLines[cluster.lineIndices[b]];

                // Skip if lines are too parallel (theta difference < 2 degrees)
                double thetaDiff = std::abs(l1.theta - l2.theta);
                if (thetaDiff < 2.0 * M_PI / 180.0) continue;

                // Solve 2x2 system:
                // cos(t1)*x + sin(t1)*y = rho1
                // cos(t2)*x + sin(t2)*y = rho2
                double c1 = std::cos(l1.theta), s1 = std::sin(l1.theta);
                double c2 = std::cos(l2.theta), s2 = std::sin(l2.theta);
                double det = c1 * s2 - c2 * s1;
                if (std::abs(det) < 1e-10) continue;  // parallel

                double ix = (l1.rho * s2 - l2.rho * s1) / det;
                double iy = (l2.rho * c1 - l1.rho * c2) / det;

                // Filter out intersection points that are absurdly far away
                // (more than 5x image diagonal from image center)
                double diagLen = std::sqrt((double)(imgWidth * imgWidth + imgHeight * imgHeight));
                double cx = imgWidth * 0.5, cy = imgHeight * 0.5;
                double dist = std::sqrt((ix - cx) * (ix - cx) + (iy - cy) * (iy - cy));
                if (dist > 5.0 * diagLen) continue;

                xs.push_back(ix);
                ys.push_back(iy);
                pairCount++;
            }
        }

        if (xs.size() < 3) {
            VE_LOG("EstimateVanishingPoints: cluster %d has too few intersections (%d)", ci, (int)xs.size());
            continue;
        }

        // Median intersection point (robust to outliers)
        std::sort(xs.begin(), xs.end());
        std::sort(ys.begin(), ys.end());
        double medX = xs[xs.size() / 2];
        double medY = ys[ys.size() / 2];

        VanishingPointEstimate vp;
        vp.x = medX;
        vp.y = medY;
        vp.lineCount = nLines;
        vp.dominantAngle = cluster.avgTheta;
        // Confidence: ratio of this cluster's votes to total votes, capped at 1.0
        int totalAllVotes = 0;
        for (auto& c : clusters) totalAllVotes += c.totalVotes;
        vp.confidence = (totalAllVotes > 0) ?
            std::min(1.0, (double)cluster.totalVotes / (double)totalAllVotes * 2.0) : 0.0;

        results.push_back(vp);
        VE_LOG("EstimateVanishingPoints: VP%d at (%.1f, %.1f) conf=%.2f lines=%d angle=%.1f°",
               ci, medX, medY, vp.confidence, nLines, cluster.avgTheta * 180.0 / M_PI);
    }

    return results;
}

//========================================================================================
//  C-callable wrappers
//========================================================================================

int PluginVisionLoadImage(const char* filePath)
{
    return VisionEngine::Instance().LoadImage(filePath) ? 1 : 0;
}

int PluginVisionIsLoaded()
{
    return VisionEngine::Instance().IsLoaded() ? 1 : 0;
}

int PluginVisionGetWidth()
{
    return VisionEngine::Instance().Width();
}

int PluginVisionGetHeight()
{
    return VisionEngine::Instance().Height();
}

//========================================================================================
//  Surface type inference (Gap 1)
//========================================================================================

void VisionEngine::ArtToPixelMapping::ArtRectToPixelRect(
    double aLeft, double aTop, double aRight, double aBottom,
    int& pX, int& pY, int& pW, int& pH) const
{
    if (!valid || pixelWidth == 0 || pixelHeight == 0) {
        pX = pY = pW = pH = 0;
        return;
    }
    double artW = artRight - artLeft;
    double artH = artTop - artBottom;  // Illustrator Y-up: top > bottom
    if (artW < 1e-6 || artH < 1e-6) { pX = pY = pW = pH = 0; return; }

    double scaleX = pixelWidth / artW;
    double scaleY = pixelHeight / artH;

    // Artwork coords: origin bottom-left, Y-up. Pixel coords: origin top-left, Y-down.
    pX = (int)((aLeft - artLeft) * scaleX);
    pY = (int)((artTop - aTop) * scaleY);   // flip Y
    pW = (int)((aRight - aLeft) * scaleX);
    pH = (int)((aTop - aBottom) * scaleY);

    // Clamp to image bounds
    if (pX < 0) { pW += pX; pX = 0; }
    if (pY < 0) { pH += pY; pY = 0; }
    if (pX + pW > pixelWidth)  pW = pixelWidth - pX;
    if (pY + pH > pixelHeight) pH = pixelHeight - pY;
    if (pW < 0) pW = 0;
    if (pH < 0) pH = 0;
}

void VisionEngine::SetArtToPixelMapping(double aLeft, double aTop, double aRight, double aBottom)
{
    std::lock_guard<std::recursive_mutex> lock(mMutex);
    artMapping.artLeft   = aLeft;
    artMapping.artTop    = aTop;
    artMapping.artRight  = aRight;
    artMapping.artBottom = aBottom;
    artMapping.pixelWidth  = imgWidth;
    artMapping.pixelHeight = imgHeight;
    artMapping.valid = (imgWidth > 0 && imgHeight > 0);
    VE_LOG("SetArtToPixelMapping: art=[%.0f,%.0f,%.0f,%.0f] px=[%d,%d] valid=%d",
           aLeft, aTop, aRight, aBottom, imgWidth, imgHeight, artMapping.valid);
}

VisionEngine::SurfaceHint VisionEngine::InferSurfaceType(int x, int y, int w, int h)
{
    std::lock_guard<std::recursive_mutex> lock(mMutex);
    SurfaceHint result;
    result.type = SurfaceType::Unknown;
    result.confidence = 0.0;
    result.gradientAngle = 0.0;

    if (!IsLoaded() || w < 5 || h < 5) return result;

    // Clamp region to image bounds
    if (x < 0) { w += x; x = 0; }
    if (y < 0) { h += y; y = 0; }
    if (x + w > imgWidth)  w = imgWidth - x;
    if (y + h > imgHeight) h = imgHeight - y;
    if (w < 5 || h < 5) return result;

    // Step 1: Extract sub-region, downsample if large
    int step = 1;
    while (w / step > 200 || h / step > 200) step++;
    int sw = w / step, sh = h / step;
    if (sw < 5 || sh < 5) return result;

    std::vector<uint8_t> subImage(sw * sh);
    for (int sy = 0; sy < sh; sy++) {
        for (int sx = 0; sx < sw; sx++) {
            int srcX = x + sx * step;
            int srcY = y + sy * step;
            subImage[sy * sw + sx] = pixels[srcY * imgWidth + srcX];
        }
    }

    // Step 2: Blur and compute gradient on sub-region
    auto blurred = GaussianBlur(subImage, sw, sh, 1.5);
    Gradient grad = ComputeGradient(blurred, sw, sh);

    // Step 3: Find magnitude threshold (5% of max) to ignore noise
    double maxMag = 0;
    for (int i = 0; i < sw * sh; i++) {
        if (grad.magnitude[i] > maxMag) maxMag = grad.magnitude[i];
    }
    double magThresh = maxMag * 0.05;
    if (maxMag < 1.0) {
        // No significant gradients — flat region
        result.type = SurfaceType::Flat;
        result.confidence = 0.9;
        return result;
    }

    // Step 4: Build AXIAL gradient direction histogram (18 bins, 10 degrees each, 0..180°)
    // Gradients are axial — edges on both sides of a ridge point in opposite directions.
    // Folding to 0..π merges them into the same bin (Codex P1 fix).
    const int NBINS = 18;
    double histogram[NBINS] = {};
    double totalWeight = 0;
    int pixelsAboveThresh = 0;

    for (int i = 0; i < sw * sh; i++) {
        if (grad.magnitude[i] < magThresh) continue;
        pixelsAboveThresh++;
        double angle = grad.direction[i];  // radians, -pi to pi
        // Fold to 0..pi (axial: direction and direction+pi are the same axis)
        if (angle < 0) angle += M_PI;
        if (angle >= M_PI) angle -= M_PI;
        int bin = (int)(angle / M_PI * NBINS);
        if (bin >= NBINS) bin = NBINS - 1;
        histogram[bin] += grad.magnitude[i];
        totalWeight += grad.magnitude[i];
    }

    double activeRatio = (double)pixelsAboveThresh / (sw * sh);

    // Step 5: If very few active pixels, it's flat
    if (activeRatio < 0.15) {
        result.type = SurfaceType::Flat;
        result.confidence = 0.7 + 0.3 * (1.0 - activeRatio / 0.15);
        return result;
    }

    // Step 6: Find peaks and classify histogram shape
    int peakBin = 0;
    double peakVal = 0;
    for (int b = 0; b < NBINS; b++) {
        if (histogram[b] > peakVal) { peakVal = histogram[b]; peakBin = b; }
    }

    // Weight in peak bin + neighbors (wrapped)
    double peakWeight = histogram[peakBin]
                      + histogram[(peakBin + 1) % NBINS]
                      + histogram[(peakBin + NBINS - 1) % NBINS];
    double peakRatio = (totalWeight > 0) ? peakWeight / totalWeight : 0;

    // Dominant gradient angle from peak bin (in axial range 0..pi)
    result.gradientAngle = (peakBin + 0.5) * (M_PI / NBINS);

    // Check for cylindrical: one strong directional peak in the axial histogram
    if (peakRatio > 0.50) {
        result.type = SurfaceType::Cylindrical;
        result.confidence = 0.5 + 0.5 * (peakRatio - 0.50) / 0.50;
        if (result.confidence > 1.0) result.confidence = 1.0;
        return result;
    }

    // Check for saddle: two peaks ~45 degrees apart in axial space (= 90° in full space)
    // In 18-bin axial histogram, 45° = 4.5 bins
    int peak2Bin = -1;
    double peak2Val = 0;
    for (int b = 0; b < NBINS; b++) {
        int dist = abs(b - peakBin);
        if (dist > NBINS / 2) dist = NBINS - dist;
        if (dist < 3) continue;  // too close to first peak
        if (histogram[b] > peak2Val) { peak2Val = histogram[b]; peak2Bin = b; }
    }

    if (peak2Bin >= 0) {
        int angularDist = abs(peak2Bin - peakBin);
        if (angularDist > NBINS / 2) angularDist = NBINS - angularDist;
        double degreesDist = angularDist * (180.0 / NBINS);  // axial degrees

        double peak2Weight = histogram[peak2Bin]
                           + histogram[(peak2Bin + 1) % NBINS]
                           + histogram[(peak2Bin + NBINS - 1) % NBINS];
        double peak2Ratio = (totalWeight > 0) ? peak2Weight / totalWeight : 0;

        // Saddle: two axial peaks 35-55° apart (= 70-110° in full space), each > 15% weight
        if (degreesDist >= 35 && degreesDist <= 55 && peakRatio > 0.15 && peak2Ratio > 0.15) {
            result.type = SurfaceType::Saddle;
            result.confidence = 0.5 + 0.3 * fmin(peakRatio, peak2Ratio) / 0.25;
            if (result.confidence > 1.0) result.confidence = 1.0;
            return result;
        }
    }

    // Step 7: Broad histogram — curved surface (convex or concave).
    // Codex P1 fix: divergence sign is NOT reliable (flips with contrast polarity).
    // Instead, use absolute divergence magnitude to detect curvature WITHOUT
    // distinguishing convex from concave. Report as Convex with a note that
    // the Python MCP pipeline (DSINE normals) can refine this.
    std::vector<double> gx(sw * sh, 0), gy(sw * sh, 0);
    for (int i = 0; i < sw * sh; i++) {
        gx[i] = grad.magnitude[i] * cos(grad.direction[i]);
        gy[i] = grad.magnitude[i] * sin(grad.direction[i]);
    }

    double totalAbsDiv = 0;
    int divCount = 0;
    for (int py = 1; py < sh - 1; py++) {
        for (int px = 1; px < sw - 1; px++) {
            int idx = py * sw + px;
            if (grad.magnitude[idx] < magThresh) continue;
            double dGxdx = (gx[idx + 1] - gx[idx - 1]) * 0.5;
            double dGydy = (gy[idx + sw] - gy[idx - sw]) * 0.5;
            totalAbsDiv += fabs(dGxdx + dGydy);
            divCount++;
        }
    }

    double avgAbsDiv = (divCount > 0) ? totalAbsDiv / divCount : 0;

    if (avgAbsDiv > 0.5) {
        // Significant divergence = curved surface. Report as Convex (heuristic).
        // Python MCP override can refine to Concave when DSINE data is available.
        result.type = SurfaceType::Convex;
        result.confidence = 0.35 + 0.35 * fmin(avgAbsDiv / 3.0, 1.0);
    } else {
        // Low divergence + broad histogram = ambiguous. Default flat, low confidence.
        result.type = SurfaceType::Flat;
        result.confidence = 0.3;
    }

    if (result.confidence > 1.0) result.confidence = 1.0;
    VE_LOG("InferSurfaceType: region=[%d,%d,%dx%d] type=%d conf=%.2f angle=%.1f°",
           x, y, w, h, (int)result.type, result.confidence,
           result.gradientAngle * 180.0 / M_PI);
    return result;
}

//========================================================================================
//  ClusterNormalDirections — k-means on gradient direction histogram
//========================================================================================

std::vector<VisionEngine::PlaneCluster> VisionEngine::ClusterNormalDirections(int maxPlanes)
{
    std::lock_guard<std::recursive_mutex> lock(mMutex);
    std::vector<PlaneCluster> result;

    if (pixels.empty() || imgWidth < 2 || imgHeight < 2) return result;

    // Build high-resolution angle histogram (36 bins = 5° each, axial: 0-π)
    const int NUM_BINS = 36;
    std::vector<int> histogram(NUM_BINS, 0);
    int totalGrad = 0;

    for (int y = 1; y < imgHeight - 1; y++) {
        for (int x = 1; x < imgWidth - 1; x++) {
            int idx = y * imgWidth + x;

            // Grayscale gradient (Sobel-like)
            double gx = (double)pixels[idx + 1] - (double)pixels[idx - 1];
            double gy = (double)pixels[idx + imgWidth] - (double)pixels[idx - imgWidth];
            double mag = std::sqrt(gx * gx + gy * gy);

            if (mag < 10.0) continue;  // skip low-gradient pixels

            double angle = std::atan2(gy, gx);
            if (angle < 0) angle += M_PI;
            if (angle >= M_PI) angle -= M_PI;  // fold to 0-π

            int bin = (int)(angle / M_PI * NUM_BINS);
            if (bin >= NUM_BINS) bin = NUM_BINS - 1;
            histogram[bin]++;
            totalGrad++;
        }
    }

    if (totalGrad < 100) return result;  // too few gradient pixels

    // Find peaks: local maxima in the histogram (with wrapping for circular data)
    struct Peak { int bin; int count; double angle; };
    std::vector<Peak> peaks;

    for (int i = 0; i < NUM_BINS; i++) {
        int prev = histogram[(i - 1 + NUM_BINS) % NUM_BINS];
        int next = histogram[(i + 1) % NUM_BINS];
        if (histogram[i] > prev && histogram[i] > next && histogram[i] > totalGrad / NUM_BINS) {
            double angle = (i + 0.5) * M_PI / NUM_BINS;
            peaks.push_back({i, histogram[i], angle});
        }
    }

    // Sort peaks by count (strongest first)
    std::sort(peaks.begin(), peaks.end(), [](const Peak& a, const Peak& b) {
        return a.count > b.count;
    });

    // Take top maxPlanes peaks
    int nPlanes = std::min((int)peaks.size(), maxPlanes);
    for (int i = 0; i < nPlanes; i++) {
        PlaneCluster pc;
        pc.normalAngle = peaks[i].angle;
        pc.strength = (double)peaks[i].count / (double)totalGrad;
        pc.pixelCount = peaks[i].count;
        result.push_back(pc);

        VE_LOG("ClusterNormals: plane %d angle=%.1f° strength=%.2f (%d pixels)",
               i, pc.normalAngle * 180.0 / M_PI, pc.strength, pc.pixelCount);
    }

    return result;
}

//========================================================================================
//  EstimateVPsFromNormals — derive VPs from dominant surface plane orientations
//========================================================================================

std::vector<VisionEngine::VanishingPointEstimate> VisionEngine::EstimateVPsFromNormals(int maxVPs)
{
    std::lock_guard<std::recursive_mutex> lock(mMutex);
    std::vector<VanishingPointEstimate> result;

    // Get dominant plane clusters
    auto planes = ClusterNormalDirections(maxVPs + 1);  // get extra for filtering
    if (planes.size() < 1) return result;

    // Each plane's gradient direction indicates the surface normal.
    // The EDGE direction of that plane is perpendicular to the gradient.
    // Parallel edges from the same plane family converge at a VP.
    // The VP direction is along the edge direction (gradient + π/2).

    double imgCx = imgWidth * 0.5;
    double imgCy = imgHeight * 0.5;

    for (int i = 0; i < (int)planes.size() && (int)result.size() < maxVPs; i++) {
        // Edge direction = gradient direction + 90°
        double edgeAngle = planes[i].normalAngle + M_PI / 2.0;
        if (edgeAngle >= M_PI) edgeAngle -= M_PI;

        // Place VP far along the edge direction from image center
        // Distance proportional to image size (VPs are typically far from image)
        double vpDist = std::max(imgWidth, imgHeight) * 2.0;
        double vpX = imgCx + std::cos(edgeAngle) * vpDist;
        double vpY = imgCy + std::sin(edgeAngle) * vpDist;

        // Check this VP isn't too close to an existing one
        bool tooClose = false;
        for (auto& existing : result) {
            double dx = vpX - existing.x, dy = vpY - existing.y;
            double angleDiff = std::abs(edgeAngle - existing.dominantAngle);
            if (angleDiff < M_PI / 6.0 || angleDiff > 5.0 * M_PI / 6.0) {
                tooClose = true;
                break;
            }
        }
        if (tooClose) continue;

        VanishingPointEstimate vpe;
        vpe.x = vpX;
        vpe.y = vpY;
        vpe.confidence = planes[i].strength;
        vpe.lineCount = planes[i].pixelCount;
        vpe.dominantAngle = edgeAngle;
        result.push_back(vpe);

        VE_LOG("VPFromNormals: VP%d at (%.0f, %.0f) edge_angle=%.1f° conf=%.2f",
               (int)result.size(), vpX, vpY, edgeAngle * 180.0 / M_PI, planes[i].strength);
    }

    return result;
}
