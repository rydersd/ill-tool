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
    return !pixels.empty() && imgWidth > 0 && imgHeight > 0;
}

int VisionEngine::Width() const  { return imgWidth; }
int VisionEngine::Height() const { return imgHeight; }

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
    if (!IsLoaded()) {
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
    if (!IsLoaded()) {
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
    if (!IsLoaded()) {
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
    if (!IsLoaded()) {
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
    if (initialPath.size() < 3 || !IsLoaded()) {
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
